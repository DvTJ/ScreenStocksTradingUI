"""The bot buys game upgrades on its own when they pay for themselves quickly (needs the upgrade extension).

Every CHECK_S seconds, while the bot runs for real (not in practice mode) and "buy upgrades" is on, the game's
upgrade catalog is read through the bridge (game_bridge.py). Each upgrade the bot can value gets an estimated
gain in money per minute; payback = price / gain. The upgrade with the shortest payback is bought (one level)
when the payback is within upgrade_payback_min and the price fits the budget: all purchases of the last hour
together stay within upgrade_max_pct % of the cash.

Gain per minute of one more level:
- IncomePerMinute: the income itself (next - current value).
- DividendGain: the dividends per minute times the step of the bonus ((100 + next) / (100 + current) - 1).
- BuyCooldown / ShortCooldown: the bot's own profit per minute on that side times the extra trades a shorter
  cooldown allows (current / next - 1) - only once the bot has made money on that side.
- StockVolume: the bot's profit per minute times the step of the volume bonus, scaled by the share of stocks
  whose volume limit caps the bot's stake (more volume does nothing for a stock with shares to spare).
Offline income/hours and the game's auto actions do nothing for the bot and are never bought.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from . import bot, game_bridge, settings as settings_mod
from .gui import fmt
from .i18n import t
from .storage import Storage

log = logging.getLogger(__name__)

CHECK_S = 30                 # between two looks at the catalog (and after a purchase, before the next one)
BUDGET_WINDOW_S = 3600       # upgrade_max_pct is the budget of this window
RETRY_S = 600                # an upgrade the game declined is left alone this long
MIN_TRADES = 5               # trades on a side before its profit counts for cooldown / volume upgrades
MIN_MINUTES = 10.0           # ... and minutes since the bot was switched on
GAME_DIR_S = 300             # how long a found game folder is reused before looking again


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def profit_per_min(res: dict, now_ms: int) -> dict:
    """The bot's money made per minute since activation, per side ("long" / "short"); 0 while unproven or losing."""
    since = res.get("since")
    minutes = (now_ms - since) / 60000 if since else 0.0
    out = {"long": 0.0, "short": 0.0}
    if minutes < MIN_MINUTES:
        return out
    for side in out:
        trades = [x for x in res.get("trades", []) if x.get("side") == side]
        made = sum(x["ret"] * x.get("money", 0) / 100 for x in trades)
        if len(trades) >= MIN_TRADES and made > 0:
            out[side] = made / minutes
    return out


def volume_capped(stocks: list, cash: float, trade_pct: int) -> float:
    """Share (0..1) of the unlocked stocks whose free shares are worth less than the bot's stake."""
    stake = cash * trade_pct / 100
    vals = [(_num(s.get("availableShares")) or 0.0) * (_num(s.get("price")) or 0.0)
            for s in stocks if s.get("unlocked")]
    return sum(v < stake for v in vals) / len(vals) if vals else 0.0


def gain_per_min(u: dict, dividends_min: float, profit: dict, shorts: bool, capped: float) -> Optional[float]:
    """Estimated extra money per minute of the next level of upgrade u, None when the bot cannot value it."""
    cur, nxt = _num(u.get("currentValue")), _num(u.get("nextValue"))
    if cur is None or nxt is None or u.get("maxed"):
        return None
    uid = u.get("upgradeId")
    step = (100 + nxt) / (100 + cur) - 1 if 100 + cur > 0 else 0.0
    if uid == "IncomePerMinute":
        return nxt - cur
    if uid == "DividendGain":
        return dividends_min * step
    if uid in ("BuyCooldown", "ShortCooldown") and nxt > 0:
        side = "long" if uid == "BuyCooldown" else "short"
        if side == "short" and not shorts:
            return None
        return profit[side] * (cur / nxt - 1)
    if uid == "StockVolume":
        return (profit["long"] + (profit["short"] if shorts else 0.0)) * step * capped
    return None


def choose(catalog: list, budget: float, dividends_min: float, profit: dict, shorts: bool, capped: float,
           payback_min: float, skip=()) -> tuple[Optional[dict], list]:
    """(the upgrade to buy or None, every valued upgrade with gain, price and payback) - shortest payback first."""
    rows = []
    for u in catalog:
        price = _num(u.get("nextPrice"))
        gain = gain_per_min(u, dividends_min, profit, shorts, capped)
        if price is None or gain is None or gain <= 0:
            continue
        rows.append({"id": u["upgradeId"], "name": u.get("displayName") or u["upgradeId"],
                     "level": u.get("currentLevel"), "price": price, "gain": gain, "payback": price / gain})
    rows.sort(key=lambda r: r["payback"])
    pick = next((r for r in rows if r["payback"] <= payback_min and r["price"] <= budget and r["id"] not in skip), None)
    return pick, rows


class UpgradeBuyer:
    """Runs the catalog check in its own thread: the bridge may take seconds to answer, the rules must not wait."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._next = 0.0
        self._busy = False
        self._game_dir = None
        self._game_dir_at = 0.0
        self._client: Optional[game_bridge.Client] = None
        self._spent: list = []                   # (local time, price) of the purchases of the budget window
        self._declined: dict = {}                # upgrade id -> local time until which it is left alone
        self.last: dict = {}                     # latest evaluation, for the bot tab

    def step(self, bot_settings, live: bool, loss_limit_hit: bool) -> None:
        s = bot_settings
        if not (s.enabled and s.buy_upgrades and not s.paper and live and not loss_limit_hit) \
                or not game_bridge.supported() or self._busy or time.time() < self._next:
            return
        self._busy, self._next = True, time.time() + CHECK_S
        threading.Thread(target=self._run, args=(s,), daemon=True, name="bot-upgrades").start()

    def _client_for_game(self) -> Optional[game_bridge.Client]:
        if self._game_dir is None or time.time() - self._game_dir_at > GAME_DIR_S:
            chosen = settings_mod.load().game_dir
            self._game_dir = (Path(chosen) if chosen and game_bridge.is_game_dir(Path(chosen))
                              else game_bridge.find_game_dir())
            self._game_dir_at = time.time()
        if self._game_dir is None or not (self._game_dir / game_bridge.PLUGIN_DIR / "ScreenStocksBridge.dll").is_file():
            return None
        if self._client is None or self._client.game_dir != self._game_dir:
            self._client = game_bridge.Client(self._game_dir)
        return self._client

    def budget(self, cash: float, max_pct: float, now: float) -> float:
        self._spent = [(ts, p) for ts, p in self._spent if now - ts < BUDGET_WINDOW_S]
        return cash * max_pct / 100 - sum(p for _, p in self._spent)

    def _run(self, s) -> None:
        try:
            client = self._client_for_game()
            if client is None:
                self.last = {"state": "no_extension"}
                return
            _, _, shorts = bot.effective(s)
            state = client.request("state.snapshot")
            catalog = client.upgrades()
            now = time.time()
            cash = _num(state.get("cash")) or 0.0
            self._declined = {k: v for k, v in self._declined.items() if v > now}
            db = Storage(self.db_path)
            try:
                profit = profit_per_min(bot.load_results(db), int(now * 1000))
                pick, rows = choose(catalog, self.budget(cash, s.upgrade_max_pct, now),
                                    _num(state.get("dividendIncomePerMinute")) or 0.0, profit, shorts,
                                    volume_capped(state.get("stocks") or [], cash, s.trade_pct),
                                    s.upgrade_payback_min, self._declined)
                self.last = {"state": "ok", "rows": rows[:8], "checked_ms": int(now * 1000)}
                if pick is not None:
                    self._buy(db, client, pick)
            finally:
                db.close()
        except game_bridge.BridgeError as exc:
            self.last = {"state": exc.code}
            log.debug("upgrade check: %s", exc)
        except Exception:
            log.exception("upgrade check failed")
        finally:
            self._busy = False

    def _buy(self, db: Storage, client: game_bridge.Client, pick: dict) -> None:
        try:
            res = client.purchase(pick["id"], 1)
        except game_bridge.BridgeError as exc:
            self._declined[pick["id"]] = time.time() + RETRY_S
            msg = t("bot.upg.failed", name=pick["name"], error=exc.code)
        else:
            self._spent.append((time.time(), pick["price"]))
            msg = t("bot.upg.bought", name=pick["name"], level=res.get("levelBefore", pick["level"]) + 1,
                    price=fmt.big(pick["price"]), gain=fmt.big(pick["gain"]), payback=fmt.duration(max(1.0, pick["payback"] * 60)))
        log.info("bot: %s", msg)
        db.log_rule(int(time.time() * 1000), None, "", f"{t('bot.name')}: {msg}")
