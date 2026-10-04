"""Mean-reversion bot: trades the short-term noise around each stock's fair level.

Observed in the recorded data: 1-minute returns are strongly negatively
autocorrelated (about -0.4) - prices are a slow level plus large noise, and a
price far from its recent average comes back within a minute or two.

Signal   z = (ln price - EMA of ln price) / EMA std-dev   (time constant tau_s)
Entry    z <= -entry_z -> buy, z >= +entry_z -> short (optional), only when the
         expected move back to the average is at least min_edge_pct, the game's
         cooldown for that action is over and fewer than max_positions are open.
         Buys and shorts are on a ~85 s cooldown, so the best candidate wins.
Exit     sell/cover (no cooldown) when the price is back at the average
         (|z| <= exit_z), on a stop-loss, or after max_hold_s.

The same Strategy runs live (BotTrader, driven by the automation thread) and in
backtest(), so a backtest shows what the live bot would have done. It only
manages positions it opened itself; stocks with a foreign position are skipped.
"""

import json
import logging
import math
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Optional

from .commands import ACTIONS, CommandWriter, action_name, reason_text, status_text
from .i18n import t
from .storage import Storage

log = logging.getLogger(__name__)

SETTINGS_KEY = "bot"
STATE_KEY = "bot_state"
RESULT_TIMEOUT_S = 8.0
SIGMA_FLOOR = 0.002          # log-price noise floor, avoids huge z on dead-flat prices
REJECT_BLOCK_S = 30.0


@dataclass
class BotSettings:
    enabled: bool = False
    shorts: bool = False
    tau_s: int = 120             # averaging window of the "fair level"
    entry_z: float = 3.0         # how far from the average (in std-devs) before entering
    exit_z: float = 0.3          # close when this close to the average again
    min_edge_pct: float = 3.0    # skip trades expecting less than this move back to the average
    stop_pct: float = 12.0       # close when the position is this far under water
    max_hold_s: int = 240        # close at the latest after this long
    trade_pct: int = 25          # % of the maximum possible amount per entry
    max_positions: int = 3


def load_settings(db: Storage) -> BotSettings:
    try:
        data = json.loads(db.get_setting(SETTINGS_KEY, "{}"))
        return BotSettings(**{k: v for k, v in data.items() if k in BotSettings.__dataclass_fields__})
    except (ValueError, TypeError):
        return BotSettings()


def save_settings(db: Storage, s: BotSettings) -> None:
    db.set_setting(SETTINGS_KEY, json.dumps(asdict(s)))


class Strategy:
    """Per-stock EMA of ln(price) and its variance; pure logic, no I/O."""

    def __init__(self, s: BotSettings):
        self.s = s
        self._m: dict[str, float] = {}
        self._v: dict[str, float] = {}
        self._t: dict[str, float] = {}
        self._born: dict[str, float] = {}
        self.z: dict[str, float] = {}       # latest signal per stock (None while warming up)
        self.fair: dict[str, float] = {}    # latest average price per stock

    def update(self, sid: str, now: float, price: float) -> Optional[float]:
        """Feed one price (seconds clock). Returns z, or None while warming up."""
        if price <= 0:
            return None
        lp = math.log(price)
        last = self._t.get(sid)
        if last is None or now - last > 5 * self.s.tau_s:      # first sample or a long gap
            self._m[sid], self._v[sid], self._born[sid] = lp, SIGMA_FLOOR ** 2, now
            self._t[sid] = now
            return None
        dt = now - last
        if dt < 1:
            return self.z.get(sid)
        d = lp - self._m[sid]
        z = d / max(math.sqrt(self._v[sid]), SIGMA_FLOOR)
        a = 1 - math.exp(-dt / self.s.tau_s)
        self._m[sid] += a * d
        self._v[sid] = (1 - a) * (self._v[sid] + a * d * d)
        self._t[sid] = now
        warm = now - self._born[sid] >= self.s.tau_s
        self.z[sid] = z if warm else None
        self.fair[sid] = math.exp(self._m[sid])
        return self.z[sid]

    def orders(self, now: float, prices: dict, held: dict, buy_free: bool, short_free: bool,
               blocked: set = frozenset()) -> list[tuple]:
        """held: sid -> {side, entry_price, entry_s}. Returns [(sid, action, reason, z)]."""
        s, out = self.s, []
        for sid, h in held.items():
            price, z = prices.get(sid), self.z.get(sid)
            if price is None:
                continue
            long_ = h["side"] == "long"
            pnl = (price / h["entry_price"] - 1) * (1 if long_ else -1) * 100
            reason = None
            if pnl <= -s.stop_pct:
                reason = "stop"
            elif now - h["entry_s"] >= s.max_hold_s:
                reason = "timeout"
            elif z is not None and (z >= -s.exit_z if long_ else z <= s.exit_z):
                reason = "target"
            if reason:
                out.append((sid, "sell" if long_ else "cover", reason, z))

        slots = s.max_positions - len(held)
        best = {"buy": None, "short": None}
        for sid, z in self.z.items():
            if z is None or sid in held or sid in blocked or prices.get(sid) is None:
                continue
            price, fair = prices[sid], self.fair[sid]
            if z <= -s.entry_z and buy_free and (fair / price - 1) * 100 >= s.min_edge_pct:
                kind, strength = "buy", -z
            elif s.shorts and z >= s.entry_z and short_free and (price / fair - 1) * 100 >= s.min_edge_pct:
                kind, strength = "short", z
            else:
                continue
            if best[kind] is None or strength > best[kind][0]:
                best[kind] = (strength, sid, z)
        for kind, b in best.items():
            if b and slots > 0:
                out.append((b[1], kind, "entry", b[2]))
                slots -= 1
        return out


# --------------------------------------------------------------------------- live

class BotTrader:
    """Applies Strategy orders through the command files; one command in flight at a time."""

    def __init__(self, writer: CommandWriter):
        self.writer = writer
        self.strategy: Optional[Strategy] = None
        self._pending: Optional[tuple] = None   # (SentCommand, known ids, local send time, reason, price)
        self._blocked: dict[str, float] = {}    # sid -> local time until which entries are skipped
        self.last_z: dict[str, Optional[float]] = {}

    def _log(self, db: Storage, sid: str, msg: str) -> None:
        log.info("bot %s: %s", sid, msg)
        db.log_rule(int(time.time() * 1000), None, sid, f"{t('bot.name')} {sid}: {msg}")

    @staticmethod
    def _held(db: Storage) -> dict:
        try:
            return json.loads(db.get_setting(STATE_KEY, "{}"))
        except ValueError:
            return {}

    def step(self, db: Storage, s: BotSettings, live: bool, enabled: bool, now_s: float, server_ms: int,
             stocks: dict, positions: dict, snap: dict, event_ids: set) -> None:
        if self.strategy is None or self.strategy.s != s:
            old = self.strategy
            self.strategy = Strategy(s)
            if old:                                  # keep the learned averages when only parameters changed
                self.strategy.__dict__.update({k: v for k, v in old.__dict__.items() if k != "s"})
        prices = {sid: st["last_price"] for sid, st in stocks.items() if st["last_price"]}
        if live:
            for sid, p in prices.items():
                self.strategy.update(sid, now_s, p)
        self.last_z = dict(self.strategy.z)

        held = self._held(db)
        if self._pending:
            self._check_pending(db, held)
            return
        if not (enabled and live and s.enabled):
            return
        # forget bot positions that no longer exist in the game (closed manually)
        for sid in [k for k, h in held.items()
                    if not positions.get(sid, {}).get("shares_owned" if h["side"] == "long" else "shares_shorted")]:
            held.pop(sid)
            db.set_setting(STATE_KEY, json.dumps(held))
        blocked = {sid for sid, until in self._blocked.items() if until > now_s}
        blocked |= set(event_ids)
        blocked |= {sid for sid, p in positions.items() if sid not in held}                   # foreign position
        blocked |= {sid for sid, st in stocks.items() if not st["unlocked"]}
        buy_blocked = {sid for sid, st in stocks.items() if not (st["available_shares"] or 0) > 0}
        buy_free = (snap.get("next_buy_ms") or 0) <= server_ms
        short_free = (snap.get("next_short_ms") or 0) <= server_ms

        orders = self.strategy.orders(now_s, prices, {k: {**h, "entry_s": h["entry_s"]} for k, h in held.items()},
                                      buy_free, short_free, blocked)
        for sid, action, reason, z in orders:
            if action == "buy" and sid in buy_blocked:
                continue
            if self._send(db, sid, action, reason, prices[sid], z, s, held, now_s):
                return                                # one command per step; the writer rate-limits anyway

    def _send(self, db, sid, action, reason, price, z, s: BotSettings, held: dict, now_s: float) -> bool:
        pct = s.trade_pct if reason == "entry" else 100
        known = {r["id"] for r in db.command_results(200)}
        try:
            sent = self.writer.send(sid, action, pct)
        except Exception as exc:
            self._blocked[sid] = now_s + REJECT_BLOCK_S
            self._log(db, sid, t("rule.log.send_failed", error=exc))
            return False
        self._pending = (sent, known, time.time(), reason, price, now_s)
        zt = "" if z is None else f" z={z:+.1f}"
        self._log(db, sid, t("bot.log.sent", action=action_name(action), p=sent.percent,
                             reason=t(f"bot.reason.{reason}"), price=f"{price:.4g}") + zt)
        return True

    def _check_pending(self, db: Storage, held: dict) -> None:
        sent, known, t_sent, reason, price, now_s = self._pending
        prefix = ACTIONS[sent.action]
        new = [r for r in db.command_results(50)
               if r["id"] not in known and r["stock_id"] == sent.stock_id and (r["action"] or "").startswith(prefix)]
        if new and new[0]["status"] in ("done", "rejected", "failed"):
            res, self._pending = new[0], None
            if res["status"] == "done":
                if sent.action in ("buy", "short"):
                    held[sent.stock_id] = {"side": "long" if sent.action == "buy" else "short",
                                           "entry_price": price, "entry_s": now_s}
                else:
                    held.pop(sent.stock_id, None)
                db.set_setting(STATE_KEY, json.dumps(held))
                self._log(db, sent.stock_id, t("rule.log.done", action=action_name(sent.action), p=sent.percent))
            else:
                self._blocked[sent.stock_id] = now_s + REJECT_BLOCK_S
                self._log(db, sent.stock_id, t("event.log.rejected", status=status_text(res["status"]),
                                               reason=reason_text(res["reason"])))
        elif time.time() - t_sent > RESULT_TIMEOUT_S:
            self._pending = None
            self.writer.cancel(sent)
            self._blocked[sent.stock_id] = now_s + REJECT_BLOCK_S
            self._log(db, sent.stock_id, t("rule.log.no_response"))


# ------------------------------------------------------------------------ backtest

def backtest(db: Storage, s: BotSettings, since_ms: int, until_ms: int, buy_cd_s: float = 85,
             short_cd_s: float = 85, latency_s: int = 2, fee_pct: float = 0.0) -> dict:
    """Replay the recorded prices (1 s grid) through the same Strategy.

    Orders fill latency_s seconds after the signal at that second's price; fee_pct
    is charged on entry and exit. Equity assumes trade_pct % of equity per trade.
    """
    grids: dict[str, list[float]] = {}
    t0, t1 = since_ms // 1000, until_ms // 1000
    for sid in db.stock_ids():
        rows = db.conn.execute("SELECT time_ms, price FROM prices WHERE stock_id=? AND time_ms BETWEEN ? AND ? "
                               "ORDER BY time_ms", (sid, since_ms, until_ms)).fetchall()
        if not rows:
            continue
        by_s = {tm // 1000: p for tm, p in rows}
        last, g = rows[0][1], []
        for sec in range(t0, t1 + 1):
            last = by_s.get(sec, last)
            g.append(last)
        grids[sid] = g

    strat, held, trades = Strategy(s), {}, []
    next_buy = next_short = -1e18
    alloc = s.trade_pct / 100
    eq, peak, max_dd = 1.0, 1.0, 0.0
    n = t1 - t0 + 1
    for i in range(n - latency_s):
        now = t0 + i
        prices = {sid: g[i] for sid, g in grids.items()}
        for sid, p in prices.items():
            strat.update(sid, now, p)
        for sid, action, reason, z in strat.orders(now, prices, held, now >= next_buy, now >= next_short):
            fill = grids[sid][i + latency_s]
            if action in ("buy", "short"):
                held[sid] = {"side": "long" if action == "buy" else "short", "entry_price": fill, "entry_s": now}
                if action == "buy":
                    next_buy = now + buy_cd_s
                else:
                    next_short = now + short_cd_s
            else:
                h = held.pop(sid)
                ret = (fill / h["entry_price"] - 1) * (1 if h["side"] == "long" else -1) * 100 - 2 * fee_pct
                eq *= 1 + alloc * ret / 100
                peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak * 100)
                trades.append({"stock_id": sid, "side": h["side"], "entry_s": h["entry_s"], "exit_s": now,
                               "ret": ret, "reason": reason})
    wins = [x for x in trades if x["ret"] > 0]
    per_stock: dict[str, list[float]] = {}
    for x in trades:
        per_stock.setdefault(x["stock_id"], []).append(x["ret"])
    return {"trades": trades, "n": len(trades), "win_rate": 100 * len(wins) / len(trades) if trades else 0.0,
            "avg_ret": sum(x["ret"] for x in trades) / len(trades) if trades else 0.0,
            "median_ret": statistics.median(x["ret"] for x in trades) if trades else 0.0,
            "equity_pct": (eq - 1) * 100, "max_dd": max_dd, "hours": n / 3600,
            "per_stock": {k: (len(v), sum(v)) for k, v in per_stock.items()},
            "reasons": {r: sum(1 for x in trades if x["reason"] == r) for r in ("target", "stop", "timeout")}}
