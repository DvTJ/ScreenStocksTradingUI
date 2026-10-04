"""Mean-reversion bot that calibrates itself on the recorded price history.

Observed in the recorded data: 1-minute returns are strongly negatively
autocorrelated (about -0.4) - prices are a slow level plus large noise, and a
price far from its recent average comes back within a minute or two.

Signal   z = (ln price - EMA of ln price) / EMA std-dev   (time constant tau_s)
Entry    z <= -entry_z -> buy, z >= +entry_z -> short (optional), only when the
         expected move back to the average is at least min_edge_pct, the game's
         cooldown for that action is over and fewer than max_positions are open.
         Stake = trade_pct scaled by the signal strength (never above trade_pct).
Exit     sell/cover (no cooldown) when the price is back at the average
         (|z| <= exit_z), on a stop-loss, or after max_hold_s.

"Mini AI": at start and every recalib_min minutes the bot replays the last hours
of recorded prices for every stock with a few (tau_s, entry_z) pairs - the same
Strategy, with latency and fees - keeps the best pair per stock and trades only
the most profitable stocks. A stock that loses twice in a row is paused.

The same Strategy runs live (BotTrader, driven by the automation thread) and in
simulate(), so a backtest shows what the live bot would have done. It only
manages positions it opened itself; stocks with a foreign position are skipped.
"""

import bisect
import collections
import csv
import json
import logging
import math
import os
import subprocess
import sys
import statistics
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Optional

from .events import FINAL as EVENT_FINAL, load_settings as load_event_settings
from .commands import ACTIONS, CommandWriter, reason_text, status_text
from .gui import fmt
from .i18n import de, en, fr, t
from .storage import Storage

log = logging.getLogger(__name__)

SETTINGS_KEY = "bot"
STATE_KEY = "bot_state"
RESULTS_KEY = "bot_results"
RESULT_TIMEOUT_S = 8.0
SIGMA_FLOOR = 0.002          # log-price noise floor, avoids huge z on dead-flat prices
REJECT_BLOCK_S = 30.0
FEE_KEY = "bot_fees"
FEE_SAMPLES = 20             # recent real costs kept per stock
FEE_MIN_SAMPLES = 3          # fewer than this: the default FEE_PCT
MISSING_GRACE_S = 5.0         # a held position must be absent from the game this long before the bot forgets it
PAUSE_AFTER_LOSSES = 2       # consecutive losing trades on one stock ...
PAUSE_S = 900                # ... pause it this long
MAX_TRADES_KEPT = 500

LEVELS = ("simple", "medium", "advanced")
SLIPPAGE = 1.5               # a stop may fill this much further than stop_pct (price jumps, latency)
LATENCY_S = 2                # order fills this long after the signal
FEE_PCT = 1.4                # per side until measured per stock (see load_fees): ~0.9 % to buy + ~1.9 % to sell, halved
CALIB_WINDOW_S = 3 * 3600    # history used to calibrate
MIN_HISTORY_S = 900          # no calibration (hence no trading) with less history than this
GAP_S = 60                   # recording gaps longer than this are cut out of the history
MIN_TRADES = 3               # a stock needs this many simulated trades to count as proven
TAUS = (60, 120, 240)
ENTRY_Z_STEPS = (-0.5, 0.0, 0.5, 1.0)    # tried around the caution preset's entry_z
EVENT_COOLDOWN_S = 90         # buy / short cooldown the event trader needs free (it is shared by all stocks)
EVENT_AFTER_S = {"pump": 180, "crash": 900}     # the bot stays out of the stock this long after an event starts
PUMP_LEAD_S = 60             # the event trader buys a pump about this long before it
JUMP_FORCE = 1.5             # a jump bigger than this many times the stop's reach is always budgeted
JUMP_Q = 0.97                # quantile of the one-tick moves used as the stock's typical big jump
THINK_REPEAT_S = 60          # a stock's thought is repeated at most this often while it does not change
THINK_QUIET_S = 600          # ... or this often for the uninteresting ones
THINK_QUIET = ('excluded', 'unproven', 'locked')
WARM_S = 1800                # live: history replayed into the strategy when the bot starts, so it need not wait tau_s
NEWS_LOOKBACK_S = 120         # live: news older than this is ignored
RESULT_STOCKS = 3            # focus: top stocks kept = max(RESULT_STOCKS, 2 * max_positions)


@dataclass(frozen=True)
class Params:
    tau_s: int = 240             # averaging window of the "fair level"
    entry_z: float = 1.0         # how far from the average (in std-devs) before entering
    exit_z: float = 0.1          # close when this close to the average again
    min_edge_pct: float = 2.0    # skip trades expecting less than this move back to the average
    stop_pct: float = 15.0       # close when the position is this far under water
    max_hold_s: int = 300        # close at the latest after this long
    confirm_s: int = 8           # the unusual price must last this many seconds (ignores one-tick blips)
    max_loss_pct: float = 10.0    # most the stop-loss may cost on one trade, in % of the cash (caps the stake)
    jump_pct: float = 0.0        # typical big one-tick move (p99) of the stock, measured by the calibration; 0 = unknown
    news_s: int = 0              # 0 = off; else a "5-minute high/low" news may trigger an entry for this many seconds


# caution -> (internal parameters, max positions)
PRESETS = {
    "prudent": (Params(tau_s=240, entry_z=1.0, exit_z=0.1, min_edge_pct=2.5, stop_pct=15.0, max_hold_s=300, confirm_s=8, max_loss_pct=3.0), 1),
    "balanced": (Params(tau_s=240, entry_z=1.0, exit_z=0.1, min_edge_pct=2.5, stop_pct=15.0, max_hold_s=300, confirm_s=8, max_loss_pct=10.0), 2),
    "aggressive": (Params(tau_s=240, entry_z=1.0, exit_z=0.1, min_edge_pct=2.5, stop_pct=15.0, max_hold_s=300, confirm_s=8, max_loss_pct=20.0), 3),
}


@dataclass
class BotSettings:
    enabled: bool = False
    paper: bool = False          # practice mode: the live strategy trades a virtual wallet, no order reaches the game
    level: str = "simple"
    trade_pct: int = 25          # max % of the cash per trade
    caution: str = "balanced"    # medium+
    max_positions: int = 3       # medium+
    shorts: bool = False         # medium+
    trade_events: bool = False   # medium+: may also trade a stock while a pump/crash is close or running (else it stays out)
    excluded: list = field(default_factory=list)      # advanced: stocks the bot must not trade
    recalib_min: int = 10        # advanced: minutes between calibrations
    loss_limit_pct: float = 3.0  # advanced: no new trades once the bot lost this % of the cash since activation (0 = off)
    overrides: dict = field(default_factory=dict)     # advanced: Params fields set by hand (else calibrated)

    def __post_init__(self):
        if self.level not in LEVELS:
            self.level = "simple"
        if self.caution not in PRESETS:
            self.caution = "balanced"
        self.trade_pct = min(100, max(1, int(self.trade_pct)))
        self.max_positions = min(10, max(1, int(self.max_positions)))
        self.recalib_min = min(240, max(1, int(self.recalib_min)))
        self.loss_limit_pct = min(100.0, max(0.0, float(self.loss_limit_pct)))
        self.excluded = sorted({str(x) for x in self.excluded})
        defaults = Params()
        self.overrides = {k: type(getattr(defaults, k))(v) for k, v in dict(self.overrides).items()
                          if k in Params.__dataclass_fields__ and (float(v) > 0 or k == "exit_z")}

    @classmethod
    def from_dict(cls, data: dict) -> "BotSettings":
        """Ignores unknown keys, so files from older versions still load."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def load_settings(db: Storage) -> BotSettings:
    try:
        return BotSettings.from_dict(json.loads(db.get_setting(SETTINGS_KEY, "{}")))
    except (ValueError, TypeError, AttributeError):
        return BotSettings()


def _key(db: Storage, base: str) -> str:
    return base + "_paper" if load_settings(db).paper else base


def save_settings(db: Storage, s: BotSettings) -> None:
    db.set_setting(SETTINGS_KEY, json.dumps(asdict(s)))


def effective(s: BotSettings) -> tuple[Params, int, bool]:
    """(base params, max positions, shorts allowed) the chosen level really uses.
    Simple = the safe setup: balanced preset, no shorts."""
    if s.level == "simple":
        base, mp = PRESETS["balanced"]
        return base, mp, False
    base = PRESETS[s.caution][0]
    if s.level == "advanced" and s.overrides:
        base = replace(base, **s.overrides)
    return base, s.max_positions, s.shorts


def params_for(sid: str, base: Params, calib: dict, s: BotSettings) -> Params:
    c = calib.get(sid)
    p = c.params if c else base
    return replace(p, **s.overrides) if s.level == "advanced" and s.overrides else p


def auto_params(calib: dict, s: BotSettings) -> dict:
    """What the advanced fields show when nothing is set by hand: the median of the calibrated stocks."""
    base = PRESETS["balanced" if s.level == "simple" else s.caution][0]
    good = [c.params for c in calib.values() if c.good]
    return {k: (statistics.median(getattr(p, k) for p in good) if good else getattr(base, k))
            for k in Params.__dataclass_fields__}


def jump_p99(g: list) -> float:
    """99th percentile of the one-tick moves (%) in a 1 s price grid: how far one price change can go."""
    moves = sorted(abs(b / a - 1) * 100 for a, b in zip(g, g[1:]) if a != b and a > 0)
    return round(moves[int(JUMP_Q * (len(moves) - 1))], 1) if moves else 0.0


def size_pct(trade_pct: int, z: float, entry_z: float) -> int:
    """Stake grows with the signal: half of trade_pct at the entry threshold, all of it at twice that."""
    return max(1, round(trade_pct * min(1.0, abs(z) / (2 * entry_z))))


def stake_pct(trade_pct: int, z: float, p: Params, cash: float, free: float, price: float, available,
              buying: bool) -> int:
    """Percent of the maximum the game allows for one entry: the signal-scaled stake, but never so large that
    a stop-loss (with slippage) would cost more than p.max_loss_pct % of the cash."""
    pct = size_pct(trade_pct, z, p.entry_z)
    biggest = trade_money(price, 100, free, available, buying)         # money a 100 % order would move
    if biggest > 0:
        worst = max(p.stop_pct * SLIPPAGE, p.jump_pct)      # a stop cannot protect against a bigger one-tick jump
        allowed = cash * p.max_loss_pct / 100 / (worst / 100)
        pct = min(pct, math.floor(100 * allowed / biggest + 1e-9))
        if pct < 1:
            return 0                                        # too risky for the risk budget: no trade
    return pct


def trade_money(price: float, pct: float, cash: float, available, buying: bool) -> float:
    """Money one order moves. The game takes pct % of the largest amount it allows: all the cash can
    be used (one $PLAIN order was 9.5 M shares), a buy is also limited by the shares still available."""
    cap = cash / price if price > 0 else 0.0
    if buying and available is not None:
        cap = min(cap, available)
    return max(0.0, pct / 100 * cap) * price


def stock_limits(db: Storage) -> dict:
    """stock id -> shares still available to buy (now; ponytail: not their history)."""
    return {x["stock_id"]: x["available_shares"] for x in db.stocks()}


class Strategy:
    """Per-stock EMA of ln(price) and its variance; pure logic, no I/O."""

    def __init__(self, default: Params = Params(), max_positions: int = 3, shorts: bool = False):
        self.default, self.max_positions, self.shorts = default, max_positions, shorts
        self.per: dict[str, Params] = {}    # per-stock parameters (calibrated); others use the default
        self._m: dict[str, float] = {}
        self._v: dict[str, float] = {}
        self._t: dict[str, float] = {}
        self._born: dict[str, float] = {}
        self.z: dict[str, float] = {}       # latest signal per stock (None while warming up)
        self.fair: dict[str, float] = {}    # latest average price per stock
        self._since: dict[str, tuple] = {}  # sid -> (below/above, when |z| first reached the entry threshold)
        self.news: dict[str, tuple] = {}    # sid -> (when, "high"/"low") latest market news

    def p(self, sid: str) -> Params:
        return self.per.get(sid, self.default)

    def update(self, sid: str, now: float, price: float) -> Optional[float]:
        """Feed one price (seconds clock). Returns z, or None while warming up."""
        if price <= 0:
            return None
        tau = self.p(sid).tau_s
        lp = math.log(price)
        last = self._t.get(sid)
        if last is None or now - last > 5 * tau:      # first sample or a long gap
            self._m[sid], self._v[sid], self._born[sid] = lp, SIGMA_FLOOR ** 2, now
            self._t[sid] = now
            return None
        dt = now - last
        if dt < 1:
            return self.z.get(sid)
        d = lp - self._m[sid]
        z = d / max(math.sqrt(self._v[sid]), SIGMA_FLOOR)
        a = 1 - math.exp(-dt / tau)
        self._m[sid] += a * d
        self._v[sid] = (1 - a) * (self._v[sid] + a * d * d)
        self._t[sid] = now
        warm = now - self._born[sid] >= tau
        self.z[sid] = z if warm else None
        self.fair[sid] = math.exp(self._m[sid])
        if self.z[sid] is not None and abs(self.z[sid]) >= self.p(sid).entry_z:
            if self._since.get(sid, (None,))[0] != (z > 0):
                self._since[sid] = (z > 0, now)
        else:
            self._since.pop(sid, None)
        return self.z[sid]

    def why_not(self, sid: str, now: float, price: float, held: Optional[dict], buy_free: bool, short_free: bool,
                cd_left: dict, n_open: int) -> tuple[str, dict]:
        """(code, text arguments): what the bot thinks about one stock right now, in the same order as orders()."""
        p, z = self.p(sid), self.z.get(sid)
        if held:
            gain = (price / held["entry_price"] - 1) * (1 if held["side"] == "long" else -1) * 100
            return "exit_wait", {"side": held["side"], "gain": f"{gain:+.1f}", "z": "?" if z is None else f"{z:+.1f}",
                                 "exit": f"{p.exit_z:g}"}
        if z is None:
            return "warmup", {"s": max(0, round(p.tau_s - (now - self._born.get(sid, now))))}
        zt = f"{z:+.1f}"
        if abs(z) < p.entry_z:
            return "calm", {"z": zt, "need": f"{p.entry_z:g}"}
        waited = now - self._since.get(sid, (None, now))[1] + 1
        if waited < p.confirm_s:
            return "confirm", {"z": zt, "waited": round(waited), "need": p.confirm_s}
        low, fair = z < 0, self.fair[sid]
        if not low and not self.shorts:
            return "no_shorts", {"z": zt}
        edge = (fair / price - 1) * 100 if low else (price / fair - 1) * 100
        if edge < p.min_edge_pct:
            return "edge", {"z": zt, "edge": f"{edge:.1f}", "need": f"{p.min_edge_pct:g}"}
        if not (buy_free if low else short_free):
            return "cooldown", {"side": "buy" if low else "short", "s": round(cd_left["buy" if low else "short"])}
        if n_open >= self.max_positions:
            return "full", {"n": self.max_positions}
        return "ready", {"z": zt, "edge": f"{edge:.1f}"}

    def news_event(self, sid: str, now: float, kind: str) -> None:
        if kind in ("high", "low"):
            self.news[sid] = (now, kind)

    def orders(self, now: float, prices: dict, held: dict, buy_free: bool, short_free: bool,
               blocked: set = frozenset()) -> list[tuple]:
        """held: sid -> {side, entry_price, entry_s (when the entry filled)}. Returns [(sid, action, reason, z)]."""
        out = []
        for sid, h in held.items():
            price, z = prices.get(sid), self.z.get(sid)
            if price is None or now < h["entry_s"]:         # no price, or the entry order has not filled yet
                continue
            p = self.p(sid)
            long_ = h["side"] == "long"
            pnl = (price / h["entry_price"] - 1) * (1 if long_ else -1) * 100
            reason = None
            if pnl <= -p.stop_pct:
                reason = "stop"
            elif now - h["entry_s"] >= p.max_hold_s:
                reason = "timeout"
            elif z is not None and (z >= -p.exit_z if long_ else z <= p.exit_z):
                reason = "target"
            if reason:
                out.append((sid, "sell" if long_ else "cover", reason, z))

        slots = self.max_positions - len(held)
        best = {"buy": None, "short": None}
        for sid, z in self.z.items():
            if z is None or sid in held or sid in blocked or prices.get(sid) is None:
                continue
            p, price, fair = self.p(sid), prices[sid], self.fair[sid]
            options = []
            n = self.news.get(sid)
            if p.news_s > 0 and n and now - n[0] <= p.news_s:       # a 5-minute high/low news is a signal by itself
                options.append((p.entry_z if n[1] == "high" else -p.entry_z, True))
            if now - self._since.get(sid, (None, now))[1] + 1 >= p.confirm_s:     # else a possible one-tick blip
                options.append((z, False))
            for zz, from_news in options:
                if zz <= -p.entry_z and buy_free and (fair / price - 1) * 100 >= p.min_edge_pct:
                    kind, strength = "buy", -zz / p.entry_z
                elif self.shorts and zz >= p.entry_z and short_free and (price / fair - 1) * 100 >= p.min_edge_pct:
                    kind, strength = "short", zz / p.entry_z
                else:
                    continue
                if from_news:
                    self.news.pop(sid, None)
                if best[kind] is None or strength > best[kind][0]:
                    best[kind] = (strength, sid, zz)
                break
        for kind, b in best.items():
            if b and slots > 0:
                out.append((b[1], kind, "entry", b[2]))
                slots -= 1
        return out


# ---------------------------------------------------------------- simulate / calibrate

def load_grids(db: Storage, since_ms: int, until_ms: int) -> tuple[list[int], dict[str, list[float]]]:
    """(seconds, grids): recorded prices on a 1 s grid (last known price carried forward), all of equal
    length, plus the real time of each grid index. Stretches where nothing was recorded (game closed) are cut out."""
    data = {}
    for sid in db.stock_ids():
        rows = db.conn.execute("SELECT time_ms, price FROM prices WHERE stock_id=? AND time_ms BETWEEN ? AND ? "
                               "ORDER BY time_ms", (sid, since_ms, until_ms)).fetchall()
        if rows:
            data[sid] = ({tm // 1000: p for tm, p in rows}, rows[0][1])
    seen = set().union(*(d[0].keys() for d in data.values()))
    secs, last_seen = [], -GAP_S - 1
    for sec in range(since_ms // 1000, until_ms // 1000 + 1):
        last_seen = sec if sec in seen else last_seen
        if sec - last_seen <= GAP_S:
            secs.append(sec)
    grids = {}
    for sid, (by_s, last) in data.items():
        g = []
        for sec in secs:
            last = by_s.get(sec, last)
            g.append(last)
        grids[sid] = g
    return secs, grids


def news_index(db: Storage, secs: list[int]) -> dict:
    """Recorded high/low news as {grid index: [(stock id, kind)]} on the grid made by load_grids()."""
    out = {}
    if not secs:
        return out
    for ms, sid, _, kind, _ in db.news(since_ms=secs[0] * 1000, limit=100000):
        i = bisect.bisect_left(secs, ms // 1000)
        if i < len(secs) and secs[i] - ms // 1000 <= 2:
            out.setdefault(i, []).append((sid, kind))
    return out


def slice_news(news: dict, a: int, b: int) -> dict:
    return {i - a: v for i, v in news.items() if a <= i < b}


def simulate(grids: dict, per: dict, trade_pct: int, max_positions: int, shorts: bool, buy_cd_s: float = 85,
             short_cd_s: float = 85, latency_s: Optional[int] = None, fee_pct: Optional[float] = None,
             capital: float = 10000.0, limits: Optional[dict] = None, news: Optional[dict] = None, fees: Optional[dict] = None) -> dict:
    """Run the Strategy over 1 s price grids. Orders fill latency_s after the signal at that
    second's price; fee_pct (or fees[sid], the measured one) is charged on entry and exit. Each order moves trade_money() of the
    free cash (shares still available for buys included); profits are added to the cash. A stock that
    loses PAUSE_AFTER_LOSSES times in a row is paused for PAUSE_S, as live."""
    limits, news = limits or {}, news or {}          # news: grid index -> [(sid, "high"/"low")]
    latency_s = LATENCY_S if latency_s is None else latency_s       # read at call time so tools can stress them
    fee_pct = FEE_PCT if fee_pct is None else fee_pct
    strat, held, trades = Strategy(Params(), max_positions, shorts), {}, []
    strat.per = per
    next_buy = next_short = -1e18
    cash = peak = capital
    max_dd = 0.0
    streak: dict[str, int] = {}              # consecutive losing trades per stock
    paused: dict[str, float] = {}            # sid -> second until which it is skipped
    n = len(next(iter(grids.values()))) if grids else 0
    for i in range(n - latency_s):
        prices = {sid: g[i] for sid, g in grids.items()}
        for sid, p in prices.items():
            strat.update(sid, i, p)
        for sid, kind in news.get(i, ()):
            if sid in grids:
                strat.news_event(sid, i, kind)
        blocked = {sid for sid, until in paused.items() if until > i}
        # one command at a time, as live: the other signals are still there next second
        for sid, action, reason, z in strat.orders(i, prices, held, i >= next_buy, i >= next_short, blocked)[:1]:
            fill = grids[sid][i + latency_s]
            if action in ("buy", "short"):
                free = cash - sum(h["money"] for h in held.values())
                pct = stake_pct(trade_pct, z, strat.p(sid), cash, free, fill, limits.get(sid), action == "buy")
                money = trade_money(fill, pct, free, limits.get(sid), action == "buy")
                if pct < 1 or money <= 0:
                    continue
                held[sid] = {"side": "long" if action == "buy" else "short", "entry_price": fill,
                             "entry_s": i + latency_s, "money": money}
                if action == "buy":
                    next_buy = i + buy_cd_s
                else:
                    next_short = i + short_cd_s
            else:
                h = held.pop(sid)
                ret = (fill / h["entry_price"] - 1) * (1 if h["side"] == "long" else -1) * 100 - 2 * (fees or {}).get(sid, fee_pct)
                pnl = h["money"] * ret / 100
                streak[sid] = streak.get(sid, 0) + 1 if ret < 0 else 0
                if streak[sid] >= PAUSE_AFTER_LOSSES:
                    streak[sid], paused[sid] = 0, i + PAUSE_S
                cash += pnl
                peak = max(peak, cash)
                max_dd = max(max_dd, (peak - cash) / peak * 100)
                trades.append({"stock_id": sid, "side": h["side"], "ret": ret, "reason": reason, "stake": h["money"],
                               "pnl": pnl, "entry_s": h["entry_s"], "exit_s": i})
    rets = [x["ret"] for x in trades]
    return {"trades": trades, "n": len(trades), "win_rate": 100 * sum(r > 0 for r in rets) / len(rets) if rets else 0.0,
            "best": max(rets, default=0.0), "worst": min(rets, default=0.0), "capital": capital, "end": cash,
            "equity_pct": (cash / capital - 1) * 100, "max_dd": max_dd, "hours": n / 3600}


@dataclass
class Calib:
    params: Params
    score: float        # net profit minus the worst trade (money) over the calibration window
    n: int
    win_rate: float
    profit: float = 0.0  # net profit (money), without the worst-trade penalty

    @property
    def good(self) -> bool:
        return self.score > 0 and self.n >= MIN_TRADES


def calibrate(grids: dict, s: BotSettings, buy_cd_s: float = 85, short_cd_s: float = 85, capital: float = 10000.0,
              limits: Optional[dict] = None, news: Optional[dict] = None,
              fees: Optional[dict] = None) -> dict[str, Calib]:
    """Best (tau_s, entry_z) per stock by net profit (in money) on the price grids."""
    base, _, shorts = effective(s)
    out = {}
    for sid, g in grids.items():
        def run(p):
            r = simulate({sid: g}, {sid: p}, s.trade_pct, 1, shorts, buy_cd_s, short_cd_s, capital=capital,
                         limits=limits, news=news, fees=fees)
            profit = r["end"] - capital
            worst = min((x["pnl"] for x in r["trades"]), default=0.0)
            return Calib(p, profit - abs(min(0.0, worst)), r["n"], r["win_rate"], profit)

        jump = jump_p99(g)
        tries = [run(replace(base, tau_s=tau, entry_z=round(base.entry_z + dz, 2), jump_pct=jump))
                 for tau in TAUS for dz in ENTRY_Z_STEPS]
        best = max(tries, key=lambda c: c.score)
        # the jump budget (measured above) is dropped on calm stocks when that scores better (ties = keep it)
        if jump <= JUMP_FORCE * base.stop_pct * SLIPPAGE:       # a calm stock: the jump budget stays only if it pays
            c = run(replace(best.params, jump_pct=0.0))
            if c.score > best.score:
                best = c
        out[sid] = best
    return out


def pick(calib: dict, max_positions: int) -> list[str]:
    """The most profitable proven stocks, best first."""
    good = sorted((sid for sid, c in calib.items() if c.good), key=lambda sid: -calib[sid].score)
    return good[:max(RESULT_STOCKS, 2 * max_positions)]


def backtest(db: Storage, s: BotSettings, since_ms: int, until_ms: int, buy_cd_s: float = 85,
             short_cd_s: float = 85, test_s: Optional[int] = None, capital: Optional[float] = None) -> Optional[dict]:
    """Walk-forward test: calibrate on the history before the test period, then trade the test period
    (the last test_s seconds of recorded time, default the second half). None when there is too little history."""
    secs, grids = load_grids(db, since_ms, until_ms)
    grids = {k: v for k, v in grids.items() if k not in s.excluded}
    n = len(next(iter(grids.values()))) if grids else 0
    mid = n // 2 if test_s is None else max(n - test_s, MIN_HISTORY_S)
    if mid < MIN_HISTORY_S or n - mid < 60:
        return None
    capital = capital or (db.latest_snapshot() or {}).get("cash") or 10000.0
    limits, news = stock_limits(db), news_index(db, secs)
    lo = max(0, mid - CALIB_WINDOW_S)
    calib = calibrate({k: g[lo:mid] for k, g in grids.items()}, s, buy_cd_s, short_cd_s,
                      capital, limits, slice_news(news, lo, mid), load_fees(db))
    base, max_pos, shorts = effective(s)
    chosen = pick(calib, max_pos)
    per = {sid: params_for(sid, base, calib, s) for sid in chosen}
    res = simulate({sid: grids[sid][mid:] for sid in chosen}, per, s.trade_pct, max_pos, shorts, buy_cd_s, short_cd_s,
                   capital=capital, limits=limits, news=slice_news(news, mid, n), fees=load_fees(db))
    res["hours"] = (n - mid) / 3600
    res["stocks"] = chosen
    res["times_ms"] = [x * 1000 for x in secs[mid:]]       # real time of each simulated second
    res["cooldowns"] = (buy_cd_s, short_cd_s)
    return res


# ------------------------------------------------------------------------------ results

def load_results(db: Storage) -> dict:
    """{"since": ms or None, "cash0": cash at activation, "trades": [{ts, sid, side, ret, money}]} of the current activation."""
    try:
        data = json.loads(db.get_setting(_key(db, RESULTS_KEY), "{}"))
    except ValueError:
        data = {}
    return {"since": data.get("since"), "trades": data.get("trades", []), "cash0": data.get("cash0")}


def save_results(db: Storage, res: dict) -> None:
    db.set_setting(_key(db, RESULTS_KEY), json.dumps(res))


def delete_trade(db: Storage, ts: int) -> None:
    """Hide one trade (by its timestamp) from the lists; it keeps counting for the loss limit and the practice wallet."""
    res = load_results(db)
    for x in res["trades"]:
        if x["ts"] == ts:
            x["hidden"] = True
    save_results(db, res)


def _fee_raw(db: Storage) -> dict:
    try:
        raw = json.loads(db.get_setting(FEE_KEY, "{}"))
    except ValueError:
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def load_fees(db: Storage) -> dict:
    """stock -> cost per side (%) of our own orders, FEE_PCT while unmeasured: the mean of the median cost of buying
    and the median cost of selling (the game's sell spread, ~1.9 %, is about twice the buy one, ~0.9 %). Measured on
    $PLAIN with 5-10 M shares: cost = 0.6 + 0.04 / M shares in, 1.7 + 0.03 / M shares out, so a smaller stake saves
    almost nothing. ponytail: size is not modelled; a different stake needs fresh fills."""
    return {sid: min(4.0, max(0.3, (statistics.median(v["in"]) + statistics.median(v["out"])) / 2))
            for sid, v in _fee_raw(db).items() if min(len(v.get("in", ())), len(v.get("out", ()))) >= FEE_MIN_SAMPLES}


def record_fee(db: Storage, sid: str, side: str, cost_pct: float) -> None:
    """Remember what one real fill cost versus the signal price (positive = worse); side is "in" or "out"."""
    raw = _fee_raw(db)
    v = raw.setdefault(sid, {"in": [], "out": []})
    v[side] = (v.get(side, []) + [round(cost_pct, 3)])[-FEE_SAMPLES:]
    db.set_setting(FEE_KEY, json.dumps(raw))


def paper_wallet(res: dict, held: dict) -> tuple[float, float]:
    """(virtual cash, part of it free) of the practice mode: the cash at activation plus the closed trades."""
    cash = (res.get("cash0") or 0.0) + sum(x["ret"] * x.get("money", 0) / 100 for x in res["trades"])
    return cash, cash - sum(h.get("money", 0) for h in held.values())


def loss_limit_reached(res: dict, limit_pct: float) -> bool:
    """True once the money lost since activation exceeds limit_pct % of the cash at activation."""
    cash0 = res.get("cash0")
    if not limit_pct or not cash0:
        return False
    return sum(x["ret"] * x.get("money", 0) / 100 for x in res["trades"]) <= -cash0 * limit_pct / 100


def trade_history(res: dict) -> dict:
    """The trades of the current activation, newest first, with money made and per-stock totals (for the details view)."""
    rows, per = [], {}
    for x in sorted(shown(res["trades"]), key=lambda x: x["ts"], reverse=True):
        money = x.get("money", 0)
        row = {"time_ms": x["ts"], "stock_id": x["sid"], "side": x["side"], "ret": x["ret"], "money": money,
               "pnl": x["ret"] * money / 100, "entry": x.get("entry"), "exit": x.get("exit"), "reason": x["reason"],
               "held_s": x.get("held_s")}
        rows.append(row)
        v = per.setdefault(x["sid"], {"n": 0, "profit": 0.0, "wins": 0})
        v["n"] += 1
        v["profit"] += row["pnl"]
        v["wins"] += x["ret"] > 0
    wins = sum(v["wins"] for v in per.values())
    return {"since": res.get("since"), "cash0": res.get("cash0"), "trades": rows, "per_stock": per, "n": len(rows),
            "profit": sum(r["pnl"] for r in rows), "win_rate": 100 * wins / len(rows) if rows else 0.0}


def export_trades_csv(res: dict, path) -> None:
    """The trades as a CSV file (comma separated, UTF-8 with BOM so spreadsheets read the accents)."""
    cols = [("time", "common.time"), ("stock", "common.stock"), ("side", "bot.col_side"), ("return_pct", "bot.col_return"),
            ("money_used", "bot.col_stake"), ("profit", "bot.col_profit"), ("entry_price", "bot.col_entry"),
            ("exit_price", "bot.col_exit"), ("duration_s", "bot.col_held"), ("closed_because", "bot.col_reason")]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([t(k) for _, k in cols])
        for r in reversed(trade_history(res)["trades"]):            # oldest first in the file
            reason = "bot.reason.target_loss" if r["reason"] == "target" and r["pnl"] < 0 else f"bot.reason.{r['reason']}"
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["time_ms"] / 1000)), r["stock_id"],
                        t(f"side.{r['side']}"), round(r["ret"], 3), round(r["money"]), round(r["pnl"]), r["entry"],
                        r["exit"], r["held_s"], t(reason)])


def shown(trades: list) -> list:
    return [x for x in trades if not x.get("hidden")]


def summarize(trades: list) -> dict:
    """gain = money made (estimated from the stake of each trade). Deleted (hidden) trades are left out."""
    trades = shown(trades)
    rets = [x["ret"] for x in trades]
    return {"n": len(trades), "gain": sum(x["ret"] * x.get("money", 0) / 100 for x in trades),
            "win_rate": 100 * sum(r > 0 for r in rets) / len(rets) if rets else 0.0,
            "best": max(trades, key=lambda x: x["ret"], default=None),
            "worst": min(trades, key=lambda x: x["ret"], default=None)}


def report(db: Storage, calib: dict, test: Optional[dict] = None, thoughts=()) -> dict:
    """Everything needed to judge (or share) how the bot is doing: setup, calibration, live results,
    open positions, journal and the last history test."""
    s = load_settings(db)
    base, max_pos, shorts = effective(s)
    res = load_results(db)
    snap = db.latest_snapshot() or {}
    prefix = f"{t('bot.name')}: "
    return {
        "format": "screenstocks-bot-report", "version": 1, "exported_ms": int(time.time() * 1000),
        "settings": asdict(s), "effective": {"params": asdict(base), "max_positions": max_pos, "shorts": shorts},
        "cash": snap.get("cash"), "net_worth": snap.get("net_worth"),
        "stocks": [{k: x[k] for k in ("stock_id", "last_price", "max_volume", "available_shares")} for x in db.stocks()],
        "calibration": {sid: {**asdict(c.params), "score": c.score, "trades": c.n, "win_rate": c.win_rate, "profit": c.profit,
                              "good": c.good} for sid, c in calib.items()},
        "results": res, "summary": {k: v for k, v in summarize(res["trades"]).items()},
        "positions": json.loads(db.get_setting(_key(db, STATE_KEY), "{}")),
        "journal": [{"time_ms": ts, "message": msg[len(prefix):]} for _, ts, _, _, msg in db.rule_log(500)
                    if msg.startswith(prefix)],
        "thoughts": [{"time_ms": ms, "stock_id": sid, "message": msg} for ms, sid, msg, _code in thoughts],
        "history_test": test and {k: v for k, v in test.items() if k not in ("times_ms",)},
    }


# ------------------------------------------------------- shared by the Tk tab and the web tab

TEST_RANGES = {"15m": 900, "30m": 1800, "1h": 3600, "3h": 10800, "6h": 21600, "24h": 86400, "all": None}
BREAKDOWN_PERIODS = (900, 1800, 3600, 10800, 21600)       # "last 15 min / 1 h / 3 h / 6 h" of a history test


def plural(key: str, n: int) -> str:
    return t(f"{key}.{'one' if n == 1 else 'many'}", n=n)


def state_sentence(s: BotSettings, engine_state: str, trader: "BotTrader", held: dict) -> tuple[str, str]:
    """One plain sentence about what the bot is doing, and its tone: "ok", "warn" or "" (neutral)."""
    if not s.enabled:
        return t("bot.state.off"), "warn"
    if engine_state == "paused" and not s.paper:
        return t("bot.state.wait_auto"), "warn"
    if engine_state not in ("active", "paused"):
        return t("bot.state.wait_game"), "warn"
    if not trader.calibrated:
        return t("bot.state.learning"), ""
    if not trader.calib:
        return t("bot.state.no_history"), "warn"
    if trader.loss_limit_hit:
        return t("bot.state.loss_limit"), "warn"
    if not trader.allowed:
        return t("bot.state.no_good"), "warn"
    return t("bot.state.active_paper" if s.paper else "bot.state.active", stocks=plural("bot.n_stocks", len(trader.allowed)),
             positions=plural("bot.n_positions", len(held))), "ok"


def run_test(db_path, s: BotSettings, test_s: Optional[int], capital: Optional[float] = None) -> tuple[str, Optional[dict]]:
    """Walk-forward history test on a private connection (it takes a few seconds: run it off the UI thread).
    capital None = all the cash owned. Returns (readable summary, result or None when history is too short)."""
    db = Storage(db_path)
    try:
        snap = db.latest_snapshot() or {}
        cds = (snap.get("buy_cooldown_s") or 85, snap.get("short_cooldown_s") or 85)
        capital = capital or snap.get("cash") or 10000.0
        res = backtest(db, s, db.first_time_ms() or 0, db.latest_time_ms() or 0, *cds, test_s=test_s, capital=capital)
    finally:
        db.close()
    if res is None:
        return t("bot.test.too_short"), None
    profit = res["end"] - capital
    text = (t("bot.test.result", hours=f"{res['hours']:.1f}", n=res["n"], start=fmt.num(capital, 0),
              end=fmt.num(res["end"], 0), gain=("+" if profit >= 0 else "") + fmt.num(profit, 0),
              win=f"{res['win_rate']:.0f}", stocks=len(res["stocks"]))
            + "\n" + t("bot.test.warning", fee=fmt.num(FEE_PCT, 1), latency=LATENCY_S,
                       buy=f"{res['cooldowns'][0]:g}", short=f"{res['cooldowns'][1]:g}"))
    return text, res


def with_times(res: dict) -> dict:
    """A history test with the real time (ms) on every trade instead of second indexes."""
    out = {k: v for k, v in res.items() if k != "times_ms"}
    out["trades"] = [{**x, "entry_time_ms": res["times_ms"][x["entry_s"]], "exit_time_ms": res["times_ms"][x["exit_s"]]}
                     for x in res["trades"]]
    return out


def test_breakdown(res: dict) -> dict:
    """Detail of a history test: profit per stock, stats of the last 15 min / 1 h / 3 h / 6 h, every trade."""
    total = res["hours"] * 3600
    per: dict[str, list] = {}
    for x in res["trades"]:
        per.setdefault(x["stock_id"], []).append(x["pnl"])
    periods = []
    for w in BREAKDOWN_PERIODS:
        if w < total:
            part = [x for x in res["trades"] if x["exit_s"] >= total - w]
            wins = sum(x["ret"] > 0 for x in part)
            periods.append({"seconds": w, "n": len(part), "win_rate": 100 * wins / len(part) if part else None,
                            "profit": sum(x["pnl"] for x in part)})
    return {"per_stock": {sid: {"n": len(v), "profit": sum(v)} for sid, v in sorted(per.items())},
            "periods": periods, "trades": with_times(res)["trades"]}


def save_report(db: Storage, calib: dict, test: Optional[dict], path, thoughts=()) -> None:
    """Write report() to a JSON file; the history test (if any) gets real times on its trades."""
    data = report(db, calib, with_times(test) if test else None, thoughts)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)


def reveal(path) -> None:
    """Show a file in the system file manager (Explorer selects it on Windows)."""
    path = os.path.normpath(str(path))
    if sys.platform == "win32":
        subprocess.Popen(f'explorer /select,"{path}"')       # one string: Explorer rejects a quoted /select,path argument
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def clear_history(db: Storage, trader: Optional["BotTrader"] = None) -> None:
    """Forget the trades of the current mode (real or practice), the bot's journal lines (in every language) and its
    thoughts, pauses and loss streaks. Open positions stay. A running bot gets a fresh results sheet (so its loss limit
    and the practice wallet start over from the cash now); a stopped one gets an empty sheet."""
    snap = db.latest_snapshot() or {}
    fresh = {"since": int(time.time() * 1000), "trades": [], "cash0": snap.get("cash")}
    save_results(db, fresh if load_settings(db).enabled else {})
    for lang in (de, en, fr):
        db.conn.execute("DELETE FROM rule_log WHERE message LIKE ?", (f"{lang.STRINGS['bot.name']}: %",))
    db.conn.commit()
    if trader:
        trader.thoughts.clear()
        trader._last_think.clear()
        trader._streak.clear()
        trader._blocked.clear()


def export_setup(db: Storage, path) -> None:
    """The bot setup alone, saved switched off, to share."""
    data = {"format": "screenstocks-automation", "version": 1, "bot": {**asdict(load_settings(db)), "enabled": False}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def import_setup(db: Storage, path) -> None:
    """Load the bot block of a shared file; the on/off switch keeps its current value.
    Raises ValueError (or OSError) for a file without a bot setup."""
    with open(path, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not isinstance(data.get("bot"), dict):
        raise ValueError(t("bot.import_none"))
    save_settings(db, BotSettings.from_dict({**data["bot"], "enabled": load_settings(db).enabled}))


# --------------------------------------------------------------------------- live

class BotTrader:
    """Applies Strategy orders through the command files; one command in flight at a time."""

    def __init__(self, writer: CommandWriter):
        self.writer = writer
        self.strategy = Strategy()
        self.calib: dict[str, Calib] = {}
        self.calibrated = False                 # a calibration has finished at least once
        self.calibrating = False
        self.allowed: Optional[set] = None      # stocks the bot may open positions in (None until calibrated)
        self._calib_at = 0.0
        self._calib_key = None
        self._pending: Optional[dict] = None
        self._missing: dict[str, float] = {}    # sid -> local time its position was first seen missing
        self._blocked: dict[str, float] = {}    # sid -> local time until which entries are skipped
        self._streak: dict[str, int] = {}       # consecutive losing trades per stock
        self._was_enabled: Optional[bool] = None
        self._paper_next = {"buy": 0.0, "short": 0.0}      # practice mode: own buy / short cooldowns (local seconds)
        self.thoughts: collections.deque = collections.deque(maxlen=1000)    # (time_ms, stock id, text, code), oldest first
        self._last_think: dict[str, tuple] = {}
        self._warmed: set = set()
        self.last_check_ms = 0                  # the last time the strategy was evaluated (shows the bot is alive)
        self.watching = 0
        self.fees: dict = {}                    # stock -> measured cost per side (%), see load_fees
        self._news_seen: set = set()            # (created_ms, stock id) of news already given to the strategy
        self.loss_limit_hit = False             # the bot lost loss_limit_pct % of the cash since activation

    @staticmethod
    def _save_held(db: Storage, held: dict) -> None:
        db.set_setting(_key(db, STATE_KEY), json.dumps(held))

    def _say(self, sid: str, code: str, now_s: float, force: bool = False, **args) -> None:
        """One line of "what the bot thinks", throttled: only when a stock's thought changes (or now and then)."""
        last = self._last_think.get(sid)
        if not force and last and last[0] == code and now_s - last[1] < (THINK_QUIET_S if code in THINK_QUIET else THINK_REPEAT_S):
            return
        self._last_think[sid] = (code, now_s)
        if "side" in args:
            args["side"] = t(f"bot.think.side_{args['side']}")
        self.thoughts.append((int(time.time() * 1000), sid, t(f"bot.think.{code}", sid=sid, **args), code))

    def _prewarm(self, db: Storage, now_s: float, sids) -> None:
        """Feed the recorded prices of the last WARM_S seconds to the strategy once per stock, so it has a signal right
        after a start (without it a restart needs tau_s seconds of live prices before it can trade)."""
        todo = [sid for sid in sids if sid not in self._warmed]
        last = db.latest_time_ms() if todo else None
        self._warmed |= set(todo)
        if not last:
            return
        grids = load_grids(db, last - WARM_S * 1000, last)[1]
        for sid in todo:
            g = grids.get(sid, [])
            for i, price in enumerate(g):
                self.strategy.update(sid, now_s - (len(g) - i), price)

    def _log(self, db: Storage, sid: str, msg: str) -> None:
        log.info("bot %s: %s", sid, msg)
        db.log_rule(int(time.time() * 1000), None, sid, f"{t('bot.name')}: {msg}")

    @staticmethod
    def held(db: Storage) -> dict:
        try:
            return json.loads(db.get_setting(_key(db, STATE_KEY), "{}"))
        except ValueError:
            return {}

    # -------------------------------------------------------------------- calibration

    def _maybe_calibrate(self, db: Storage, s: BotSettings, now_s: float, snap: dict) -> None:
        key = (s.level, s.caution, s.shorts, tuple(sorted(s.overrides.items())), tuple(s.excluded))
        due = not self.calibrated or (s.enabled and (key != self._calib_key
                                                     or now_s - self._calib_at >= s.recalib_min * 60))
        if self.calibrating or not due:
            return
        self.calibrating, self._calib_at, self._calib_key = True, now_s, key
        cds = (snap.get("buy_cooldown_s") or 85, snap.get("short_cooldown_s") or 85)
        threading.Thread(target=self._calibrate, args=(db.path, s, cds), daemon=True, name="bot-calib").start()

    def _calibrate(self, path, s: BotSettings, cds: tuple) -> None:
        db = Storage(path)           # own connection: this runs beside the automation thread
        try:
            end = db.latest_time_ms() or 0
            start = max(db.first_time_ms() or 0, end - CALIB_WINDOW_S * 1000)
            secs, all_grids = load_grids(db, start, end)
            grids = {k: v for k, v in all_grids.items() if k not in s.excluded}
            if len(next(iter(grids.values()), ())) < MIN_HISTORY_S:
                grids = {}
            self.calib = calibrate(grids, s, *cds, capital=(db.latest_snapshot() or {}).get("cash") or 10000.0,
                                   limits=stock_limits(db), news=news_index(db, secs), fees=load_fees(db))
            log.info("bot calibrated: %s", {k: (c.params.tau_s, c.params.entry_z, round(c.score, 1), c.n)
                                            for k, c in self.calib.items()})
        except Exception:
            log.exception("bot calibration failed")
        finally:
            db.close()
            self.calibrated, self.calibrating = True, False

    # ------------------------------------------------------------------------ step

    @staticmethod
    def _covering(p: Params, fee: float) -> Params:
        """The expected move back must cover the measured round trip cost of this stock."""
        return replace(p, min_edge_pct=max(p.min_edge_pct, 2 * fee))

    def step(self, db: Storage, s: BotSettings, live: bool, enabled: bool, now_s: float, server_ms: int,
             stocks: dict, positions: dict, snap: dict) -> None:
        base, max_pos, shorts = effective(s)
        st = self.strategy
        st.default, st.max_positions, st.shorts = base, max_pos, shorts
        self.fees = load_fees(db)
        st.per = {sid: self._covering(params_for(sid, base, self.calib, s), self.fees.get(sid, FEE_PCT)) for sid in stocks}
        prices = {sid: x["last_price"] for sid, x in stocks.items() if x["last_price"]}
        if live:
            self._prewarm(db, now_s, prices)
            for sid, p in prices.items():
                st.update(sid, now_s, p)
            for ms, sid, _, kind, _ in reversed(db.news(since_ms=server_ms - NEWS_LOOKBACK_S * 1000, limit=50)):
                if (ms, sid) not in self._news_seen:
                    self._news_seen.add((ms, sid))
                    st.news_event(sid, now_s - max(0.0, (server_ms - ms) / 1000), kind)
            self._news_seen = {k for k in self._news_seen if k[0] >= server_ms - NEWS_LOOKBACK_S * 1000}

        if s.enabled and not self._was_enabled:      # a new activation starts a fresh results sheet
            if self._was_enabled is False or not load_results(db)["since"]:
                save_results(db, {"since": int(time.time() * 1000), "trades": [], "cash0": snap.get("cash")})
        self._was_enabled = s.enabled
        if s.enabled and s.paper and not load_results(db)["cash0"]:      # practice switched on while the bot was running
            save_results(db, {"since": int(time.time() * 1000), "trades": [], "cash0": snap.get("cash")})
        self._maybe_calibrate(db, s, now_s, snap)

        held = self.held(db)
        if self._pending:
            self._check_pending(db, s, held)
            return
        self.allowed = set(pick(self.calib, max_pos)) if self.calibrated else None
        self.loss_limit_hit = loss_limit_reached(load_results(db), s.loss_limit_pct) if s.enabled else False
        if s.enabled and live and self.allowed is None:
            self._say("", "learning", now_s)
        if not ((enabled or s.paper) and live and s.enabled and self.allowed is not None):
            return
        # forget bot positions that no longer exist in the game (closed manually); practice positions are not in the game
        gone = [] if s.paper else [k for k, h in held.items()
                                   if not positions.get(k, {}).get("shares_owned" if h["side"] == "long" else "shares_shorted")]
        self._missing = {k: self._missing.get(k, now_s) for k in gone}
        for sid in [k for k in gone if now_s - self._missing[k] >= MISSING_GRACE_S]:      # not a stale / partial read
            log.warning("bot: %s no longer in the game positions, forgotten (held: %s)", sid, held[sid])
            held.pop(sid)
            self._save_held(db, held)
        why: dict[str, tuple] = {}                  # stock -> (code, args): why the bot stays out of it
        for sid, until in self._blocked.items():
            if until > now_s:
                why.setdefault(sid, ("paused", {"s": round(until - now_s)}))
        for sid, ev in ({} if s.trade_events else self.event_window(db, server_ms)).items():   # pump/crash close or running
            why.setdefault(sid, ("event", self._event_args(ev)))
        for sid in s.excluded:
            why.setdefault(sid, ("excluded", {}))
        for sid in stocks:
            if sid not in self.allowed:
                why.setdefault(sid, ("unproven", {}))
        if not s.paper:
            for sid in positions:
                if sid not in held:                                                            # foreign position
                    why.setdefault(sid, ("foreign", {}))
        for sid, x in stocks.items():
            if not x["unlocked"]:
                why.setdefault(sid, ("locked", {}))
        blocked = set(why)
        self.last_check_ms, self.watching = int(time.time() * 1000), len([x for x in prices if x not in s.excluded])
        no_stock = {sid for sid, x in stocks.items() if not (x["available_shares"] or 0) > 0}
        buy_free = (snap.get("next_buy_ms") or 0) <= server_ms
        short_free = (snap.get("next_short_ms") or 0) <= server_ms
        if s.paper:
            buy_free, short_free = now_s >= self._paper_next["buy"], now_s >= self._paper_next["short"]

        event_soon = self.event_guard(db, server_ms)
        armed = {"buy" if r["kind"] == "buy_limit" else "short" for r in db.rules(True)
                 if r["kind"] in ("buy_limit", "short_limit")}     # the game's cooldown is shared with the user's rules
        cd_left = {"buy": ((snap.get("next_buy_ms") or 0) - server_ms) / 1000, "short": ((snap.get("next_short_ms") or 0) - server_ms) / 1000}
        if s.paper:
            cd_left = {k: self._paper_next[k] - now_s for k in cd_left}
        for sid, price in prices.items():
            if sid in held:
                code, args = st.why_not(sid, now_s, price, held[sid], buy_free, short_free, cd_left, len(held))
            elif sid in why:
                code, args = why[sid]
            elif self.loss_limit_hit:
                code, args = "loss_limit", {}
            elif event_soon:
                code, args = "event_soon", self._event_args(event_soon)
            elif armed:
                code, args = "rule_armed", {"kind": "/".join(sorted(armed))}
            else:
                code, args = st.why_not(sid, now_s, price, None, buy_free, short_free, cd_left, len(held))
            if code != "excluded":                   # you chose that one yourself: no need to say it
                self._say(sid, code, now_s, **args)
        for sid, action, reason, z in st.orders(now_s, prices, held, buy_free, short_free, blocked):
            if reason == "entry" and event_soon:             # keep the cooldowns free for the event trader
                continue
            if action == "buy" and sid in no_stock:
                continue
            if reason == "entry" and action in armed:          # keep the cooldown free for the user's own limit rule
                continue
            if reason == "entry" and self.loss_limit_hit:      # closing positions stays allowed
                continue
            if reason == "entry":
                self._decision(db, s, held, sid, action, prices[sid], z, now_s, stocks[sid], snap)
            if s.paper:
                self._paper_trade(db, s, held, sid, action, reason, prices[sid], z, now_s, stocks[sid], snap)
                return                                # one command per step, as live
            h, own = held.get(sid), 100
            have = positions.get(sid, {}).get("shares_owned" if action == "sell" else "shares_shorted") or 0
            if reason != "entry" and h and h.get("shares") and have > h["shares"] * 1.01:      # bought more outside the bot
                own = max(1, int(h["shares"] / have * 100))                                    # close only the bot's part
            if self._send(db, s, sid, action, reason, prices[sid], z, now_s, stocks[sid], snap.get("cash") or 0, own):
                return                                # one command per step; the writer rate-limits anyway

    def _decision(self, db: Storage, s: BotSettings, held: dict, sid: str, action: str, price: float, z: float,
                  now_s: float, stock: dict, snap: dict) -> None:
        """Log why an entry is taken: the signal, the expected move and the stake."""
        st, buying = self.strategy, action == "buy"
        fair, p = st.fair[sid], st.p(sid)
        edge = (fair / price - 1) * 100 if buying else (price / fair - 1) * 100
        cash, free = paper_wallet(load_results(db), held) if s.paper else (snap.get("cash") or 0,) * 2
        pct = stake_pct(s.trade_pct, z, p, cash, free, price, stock["available_shares"], buying)
        waited = round(now_s - st._since.get(sid, (None, now_s))[1] + 1)
        self._say(sid, f"enter_{action}", now_s, force=True, z=f"{z:+.1f}", waited=waited, edge=f"{edge:.1f}", pct=pct,
                  jump=f"{p.jump_pct:g}")

    @staticmethod
    def _event_args(ev: dict) -> dict:
        return {"kind": t(f"event.{ev['direction']}"), "time": fmt.clock(ev["scheduled_ms"])}

    @staticmethod
    def event_window(db: Storage, server_ms: int) -> dict:
        """stock id -> event, for the events that are close or running: the bot stays out of that stock from shortly
        before the event trader acts until the price has recovered. An event announced hours ahead blocks nothing yet."""
        es, out = load_event_settings(db), {}
        for ev in db.active_events(server_ms):
            if ev["phase"] in EVENT_FINAL:
                continue
            crash = ev["direction"] != "pump"
            lead = (es.crash_minutes * 60 if crash else PUMP_LEAD_S) + EVENT_COOLDOWN_S
            if -EVENT_AFTER_S["crash" if crash else "pump"] <= (ev["scheduled_ms"] - server_ms) / 1000 <= lead:
                out[ev["stock_id"]] = ev
        return out

    @staticmethod
    def event_guard(db: Storage, server_ms: int) -> Optional[dict]:
        """The event the event trader will trade soon, if any: the game's buy / short cooldown is shared by all
        stocks, so a bot entry now could leave the event trader waiting. ponytail: not simulated (events are too rare
        in the history)."""
        es = load_event_settings(db)
        for ev in db.active_events(server_ms):
            if ev["phase"] in EVENT_FINAL or not (es.pumps if ev["direction"] == "pump" else es.crashes):
                continue
            lead = PUMP_LEAD_S if ev["direction"] == "pump" else es.crash_minutes * 60
            if ev["scheduled_ms"] - server_ms <= (lead + EVENT_COOLDOWN_S) * 1000:
                return ev
        return None

    def _paper_trade(self, db: Storage, s: BotSettings, held: dict, sid: str, action: str, reason: str, price: float,
                     z: Optional[float], now_s: float, stock: dict, snap: dict) -> None:
        """Practice mode: fill at the current price on the virtual wallet (fees as in the simulation), nothing is sent.
        ponytail: no latency, so a bit optimistic; the real fills are what the live mode measures."""
        if reason == "entry":
            cash, free = paper_wallet(load_results(db), held)
            buying = action == "buy"
            pct = stake_pct(s.trade_pct, z, self.strategy.p(sid), cash, free, price, stock["available_shares"], buying)
            money = trade_money(price, pct, free, stock["available_shares"], buying)
            if pct < 1 or money <= 0:
                return
            held[sid] = {"side": "long" if buying else "short", "entry_price": price, "entry_s": now_s,
                         "target": self.strategy.fair.get(sid), "money": money}
            cd = snap.get("buy_cooldown_s" if buying else "short_cooldown_s") or 85
            self._paper_next[action] = now_s + cd
            self._log(db, sid, t(f"bot.log.{action}", sid=sid, price=fmt.price(price), target=fmt.price(held[sid]["target"])))
        else:
            self._closed(db, held.pop(sid, None), sid, reason, price, now_s, fee_pct=2 * self.fees.get(sid, FEE_PCT))
        self._save_held(db, held)

    def _send(self, db: Storage, s: BotSettings, sid: str, action: str, reason: str, price: float,
              z: Optional[float], now_s: float, stock: dict, cash: float, close_pct: int = 100) -> bool:
        pct = (stake_pct(s.trade_pct, z, self.strategy.p(sid), cash, cash, price, stock["available_shares"],
                         action == "buy") if reason == "entry" else close_pct)
        if reason == "entry" and pct < 1:
            return False                                   # over the risk budget
        known = {r["id"] for r in db.command_results(200)}
        pos_ms = (db.conn.execute("SELECT MAX(server_ms) FROM position_history WHERE stock_id=?", (sid,)).fetchone() or [0])[0] or 0
        try:
            sent = self.writer.send(sid, action, pct)
        except Exception as exc:
            self._blocked[sid] = now_s + REJECT_BLOCK_S
            self._log(db, sid, t("rule.log.send_failed", error=exc))
            return False
        self._pending = dict(sent=sent, known=known, pos_ms=pos_ms, t=time.time(), reason=reason, price=price, now_s=now_s,
                             pct=sent.percent, target=self.strategy.fair.get(sid),
                             money=trade_money(price, sent.percent, cash, stock["available_shares"], action == "buy"))
        return True

    def _check_pending(self, db: Storage, s: BotSettings, held: dict) -> None:
        pd = self._pending
        sent = pd["sent"]
        prefix = ACTIONS[sent.action]
        new = [r for r in db.command_results(50)
               if r["id"] not in pd["known"] and r["stock_id"] == sent.stock_id
               and (r["action"] or "").startswith(prefix)]
        sid, now_s, price = sent.stock_id, pd["now_s"], pd["price"]
        if new and new[0]["status"] in ("done", "rejected", "failed"):
            res, self._pending = new[0], None
            if res["status"] != "done":
                self._blocked[sid] = now_s + REJECT_BLOCK_S
                self._log(db, sid, t("event.log.rejected", status=status_text(res["status"]),
                                     reason=reason_text(res["reason"])))
                return
            if sent.action in ("buy", "short"):
                real = self._real_entry_price(db, sent, price)
                record_fee(db, sid, "in", (real / price - 1) * 100 * (1 if sent.action == "buy" else -1))
                held[sid] = {"side": "long" if sent.action == "buy" else "short",
                             "entry_price": real,
                             "entry_s": now_s, "target": pd["target"], "money": self._real_money(db, sent, pd["money"]),
                             "shares": (db.current_positions().get(sid) or {}).get(
                                 "shares_owned" if sent.action == "buy" else "shares_shorted")}
                self._log(db, sid, t(f"bot.log.{sent.action}", sid=sid, price=fmt.price(held[sid]["entry_price"]),
                                     target=fmt.price(pd["target"])))
                self._save_held(db, held)
            else:
                h = held.get(sid)
                real = self._real_exit_price(db, sid, h, price, pd["pos_ms"])
                if real != price:
                    record_fee(db, sid, "out", (price / real - 1) * 100)
                self._closed(db, held.pop(sid, None), sid, pd["reason"], real, now_s)
                self._save_held(db, held)
        elif time.time() - pd["t"] > RESULT_TIMEOUT_S:
            self._pending = None
            self.writer.cancel(sent)
            self._blocked[sid] = now_s + REJECT_BLOCK_S
            self._log(db, sid, t("rule.log.no_response"))

    @staticmethod
    def _real_entry_price(db: Storage, sent, estimate: float) -> float:
        """The average price the game reports for the new position (its real fill), else the signal price."""
        pos = db.current_positions().get(sent.stock_id) or {}
        real = pos.get("avg_buy_price" if sent.action == "buy" else "avg_short_price") or 0.0
        return real if real > 0 else estimate

    @staticmethod
    def _real_exit_price(db: Storage, sid: str, h: Optional[dict], estimate: float, since_ms: int = 0) -> float:
        """What the game really paid for a sold long: the cash jump when the share count dropped after the order (minus
        any dividend landing in the same second) over the shares sold; partial closes included. Our own big order moves the price, so this is often 1-2 %
        under the signal price. ponytail: shorts keep the signal price (the game's cash accounting for them is unclear)."""
        if not h or h["side"] != "long" or not h.get("entry_price"):
            return estimate
        # the share-count drop caused by this order: first row after the order was sent that is below its predecessor
        rows = db.conn.execute("SELECT server_ms, shares_owned FROM position_history WHERE stock_id=? AND server_ms>=? "
                               "ORDER BY server_ms", (sid, since_ms)).fetchall()
        drop = next(((b[0], a[1] - b[1]) for a, b in zip(rows, rows[1:]) if (b[1] or 0) < (a[1] or 0)), None)
        if not drop:
            return estimate
        m, shares = drop
        before = db.conn.execute("SELECT server_ms, cash FROM snapshots WHERE server_ms<? AND cash IS NOT NULL "
                                 "ORDER BY server_ms DESC LIMIT 1", (m,)).fetchone()
        after = db.conn.execute("SELECT cash FROM snapshots WHERE server_ms>=? AND cash IS NOT NULL "
                                "ORDER BY server_ms LIMIT 1", (m,)).fetchone()
        if not before or not after:
            return estimate
        real = (after[0] - before[1] - db.dividend_sum(before[0], m)) / shares if shares > 0 else 0.0
        return real if 0.8 * estimate < real < 1.2 * estimate else estimate

    @staticmethod
    def _real_money(db: Storage, sent, estimate: float) -> float:
        """Money the game really put into the position (shares x average price), if it is already
        reported; else the estimate. The game sizes the order itself from cash and available shares."""
        pos = db.current_positions().get(sent.stock_id)
        if pos:
            real = (pos["shares_owned"] * pos["avg_buy_price"] if sent.action == "buy"
                    else pos["shares_shorted"] * pos["avg_short_price"])
            if real > 0:
                return real
        return estimate

    def _closed(self, db: Storage, h: Optional[dict], sid: str, reason: str, price: float, now_s: float,
                fee_pct: float = 0.0) -> None:
        if not h:
            return
        # ponytail: return uses the signal-time prices, not the exact fills
        ret = (price / h["entry_price"] - 1) * (1 if h["side"] == "long" else -1) * 100 - fee_pct
        res = load_results(db)
        res["trades"] = (res["trades"] + [{"ts": int(time.time() * 1000), "sid": sid, "side": h["side"],
                                           "ret": ret, "money": h.get("money", 0), "entry": h["entry_price"], "exit": price,
                                           "reason": reason, "held_s": round(now_s - h["entry_s"])}])[-MAX_TRADES_KEPT:]
        save_results(db, res)
        if reason == "target" and ret < 0:       # back to normal, but the average itself had moved against us
            reason = "target_loss"
        self._log(db, sid, t(f"bot.log.exit.{reason}", sid=sid, price=fmt.price(price), ret=fmt.pct(ret)))
        self._streak[sid] = self._streak.get(sid, 0) + 1 if ret < 0 else 0
        if self._streak[sid] >= PAUSE_AFTER_LOSSES:
            self._streak[sid] = 0
            self._blocked[sid] = now_s + PAUSE_S
            self._log(db, sid, t("bot.log.paused", sid=sid, min=PAUSE_S // 60))
