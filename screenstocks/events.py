"""Trading on events the game announces in advance (scheduledNews: "pump" / "crash").

Observed in the data:
  pump  - announced ~1 min before; at the scheduled second the price spikes to
          roughly the target (e.g. 9 -> 109 within 1 s) and falls back within ~45 s.
  crash - announced hours before; the price drifts down in the last minutes,
          drops to roughly the target for a few seconds and recovers within ~30 min.

Pump:  after the announcement sell the other long positions (cash for the pump) and
       buy -> sell close to the announced target, or once the price is X % below
       the peak after the pump really started (emergency sell N s after the
       scheduled time) -> short -> cover when the price is back near the pre-pump
       level (or after a maximum time).
Crash: N minutes before: sell the long position and open a short -> a minute before
       sell the other long positions (cash for the buy-back) -> cover and buy back
       close to the announced target, or once the price rises X % from the low
       (emergency N s after the scheduled time).

The events take precedence: reservations() tells the rules and the bot which stocks
the event trader owns and which of the game's buy / short cooldowns (shared by all
stocks) it needs soon, so they stay out of its way.

Each event runs through a small state machine whose phase is stored in the
database, so the log and the UI can show it and a restart does not repeat steps.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Optional

from .commands import ACTIONS, CommandWriter, action_name, reason_text, status_text
from .i18n import t
from .storage import Storage

log = logging.getLogger(__name__)

RESULT_TIMEOUT_S = 8.0
SETTINGS_KEY = "event_trading"
CD_DEFAULT_S = 85                     # the game's buy / short cooldown when no snapshot says otherwise
CD_MARGIN_S = 5                       # reserve a cooldown this much earlier than it is needed
PUMP_FUND_STOP_S = 10                 # pump: stop selling other positions this long before and buy with what is there
CRASH_FUND_S = 60                     # crash: sell the other long positions this long before the scheduled time
FUND_SPREAD = 1.02                    # cash needed for a buy: price x shares plus the buy spread (~0.9 %), rounded up


@dataclass
class EventSettings:
    pumps: bool = False
    crashes: bool = False
    fund_events: bool = True          # sell the other long positions so the pump buy / crash buy-back gets all the cash
    pump_buy_pct: int = 100
    pump_drop_pct: float = 10.0       # sell when the price is this far below the peak
    pump_start_share: float = 50.0    # the pump counts as started at this share of the way to the target
    pump_target_share: float = 85.0   # sell once the price got this share of the way to the target (0 = off)
    pump_safety_s: int = 30           # sell at the latest this long after the scheduled time
    pump_short_pct: int = 100         # 0 = no short after the pump
    pump_cover_pct: float = 20.0      # cover when price <= pre-pump price * (1 + x %)
    pump_cover_max_s: int = 120       # cover at the latest this long after shorting
    crash_minutes: int = 15           # sell + short this long before the crash
    crash_short_pct: int = 100        # 0 = only sell
    crash_target_pct: float = 5.0     # cover + buy back once the price is within this of the target (0 = off)
    crash_rise_pct: float = 50.0      # cover + buy back once the price rose this much from the low
    crash_safety_s: int = 120         # cover + buy back at the latest this long after the scheduled time
    crash_rebuy_pct: int = 100        # 0 = do not buy back


def load_settings(db: Storage) -> EventSettings:
    try:
        data = json.loads(db.get_setting(SETTINGS_KEY, "{}"))
        return EventSettings(**{k: v for k, v in data.items() if k in EventSettings.__dataclass_fields__})
    except (ValueError, TypeError):
        return EventSettings()


def save_settings(db: Storage, settings: EventSettings) -> None:
    db.set_setting(SETTINGS_KEY, json.dumps(asdict(settings)))


# Phases. A phase ending in "!" waits for the game's answer to a command.
PUMP_FLOW = ("wait_buy", "buy!", "hold", "sell!", "short_wait", "short!", "short_open", "cover!", "done")
CRASH_FLOW = ("wait_pre", "sell!", "short_wait", "short!", "wait_crash", "cover!", "rebuy_wait", "rebuy!", "done")
FINAL = ("done", "skipped", "failed")
# Phases in which the event trader still has to buy / short (the command not sent yet).
PUMP_BUY, PUMP_SHORT = ("wait_buy",), ("wait_buy", "buy!", "hold", "sell!", "short_wait")
CRASH_SHORT = ("wait_pre", "sell!", "short_wait")
CRASH_BUY = ("wait_pre", "sell!", "short_wait", "short!", "wait_crash", "cover!", "rebuy_wait")


def switched_on(s: EventSettings, kind: str) -> bool:
    return s.pumps if kind == "pump" else s.crashes if kind == "crash" else False


def reservations(db: Storage, s: EventSettings, now: int, snap: Optional[dict] = None) -> tuple[dict, dict]:
    """(stock id -> event, action -> event) for the events the event trader trades: the stocks it owns now and the
    buy / short cooldowns (shared by all stocks) it needs soon. The rules and the bot leave an owned stock alone and
    send no buy / short of a reserved kind, so a limit buy elsewhere cannot make the pump buy wait for the cooldown."""
    snap = snap or {}
    cd = {a: ((snap.get(f"{a}_cooldown_s") or CD_DEFAULT_S) + CD_MARGIN_S) * 1000 for a in ("buy", "short")}
    owned, reserved = {}, {}
    for ev in db.active_events(now):
        kind, phase, sched = ev["direction"], ev["phase"], ev["scheduled_ms"]
        if phase in FINAL or not switched_on(s, kind):
            continue
        if kind == "pump":                  # announced about a minute ahead: everything starts at once
            owned[ev["stock_id"]] = ev
            if phase in PUMP_BUY:
                reserved.setdefault("buy", ev)
            if phase in PUMP_SHORT and s.pump_short_pct:
                reserved.setdefault("short", ev)
            continue
        pre = sched - s.crash_minutes * 60_000          # announced hours ahead: from shortly before it acts
        if now >= pre - max(cd.values()):
            owned[ev["stock_id"]] = ev
        if phase in CRASH_SHORT and s.crash_short_pct and now >= pre - cd["short"]:
            reserved.setdefault("short", ev)
        if phase in CRASH_BUY and s.crash_rebuy_pct and now >= sched - cd["buy"]:
            reserved.setdefault("buy", ev)
    return owned, reserved


class EventTrader:
    def __init__(self, writer: CommandWriter):
        self.writer = writer
        self._pending: dict[str, tuple] = {}   # key -> (SentCommand, known ids, local send time); key = occurrence id,
        #                                        or occurrence id + "#fund" for a sell of another stock that frees cash
        self._funded: set[str] = set()         # occurrence ids whose cash is raised (or nothing was left to sell)
        self._sold: dict[str, set] = {}        # occurrence id -> stocks already sold for it (positions lag a second)
        self._market: tuple[dict, dict] = ({}, {})   # prices, positions of the current step (for the funding)
        self._busy: set[str] = set()           # stocks of all running events: never sold for another one

    # ------------------------------------------------------------------ helpers

    def _log(self, db: Storage, ev: dict, msg: str) -> None:
        log.info("event %s %s: %s", ev["stock_id"], ev["direction"], msg)
        db.log_rule(int(time.time() * 1000), None, ev["stock_id"],
                    f"{t('event.' + ev['direction'])} {ev['stock_id']}: {msg}")

    def _set(self, db: Storage, ev: dict, phase: str, **fields) -> None:
        ev.update(phase=phase, **fields)
        db.save_event_state(ev)

    def _send(self, db: Storage, ev: dict, action: str, pct: int, next_phase: Optional[str],
              stock_id: Optional[str] = None) -> bool:
        """Send a command for the event's stock and move to next_phase, or (stock_id given) sell another stock to
        free cash for the event, tracked beside the phase."""
        sid = stock_id or ev["stock_id"]
        known = {r["id"] for r in db.command_results(200)}
        try:
            sent = self.writer.send(sid, action, pct)
        except Exception as exc:
            self._log(db, ev, t("rule.log.send_failed", error=exc))
            return False
        self._pending[ev["occurrence_id"] + ("#fund" if stock_id else "")] = (sent, known, time.time())
        if next_phase:
            self._set(db, ev, next_phase)
        self._log(db, ev, t("event.log.fund_sent", sid=sid, p=sent.percent) if stock_id
                  else t("event.log.sent", action=action_name(action), p=sent.percent))
        return True

    def _result(self, db: Storage, ev: dict, key: Optional[str] = None) -> Optional[str]:
        """'done' / 'rejected' / 'timeout' once the game answered the pending command, else None."""
        key = key or ev["occurrence_id"]
        sent, known, t_sent = self._pending[key]
        prefix = ACTIONS[sent.action]
        new = [r for r in db.command_results(50)
               if r["id"] not in known and r["stock_id"] == sent.stock_id and (r["action"] or "").startswith(prefix)]
        if new and new[0]["status"] in ("done", "rejected", "failed"):
            res = new[0]
            del self._pending[key]
            if res["status"] == "done":
                self._log(db, ev, t("rule.log.done", action=action_name(sent.action), p=sent.percent))
                return "done"
            self._log(db, ev, t("event.log.rejected", status=status_text(res["status"]),
                                reason=reason_text(res["reason"])))
            return "rejected"
        if time.time() - t_sent > RESULT_TIMEOUT_S:
            del self._pending[key]
            self.writer.cancel(sent)
            self._log(db, ev, t("rule.log.no_response"))
            return "timeout"
        return None

    def _fund(self, db: Storage, ev: dict, snap: dict, price: float) -> bool:
        """Sell the other long positions, the biggest first and one per step, until the cash buys every share still
        available at `price`. True once done (enough cash, or nothing left to sell).
        ponytail: ignores the stocks' max volume (unclear whether the game caps an order with it)."""
        oid, key = ev["occurrence_id"], ev["occurrence_id"] + "#fund"
        if key in self._pending and self._result(db, ev, key) is None:
            return False
        if oid in self._funded:
            return True
        prices, positions = self._market
        avail = next((x["available_shares"] for x in db.stocks() if x["stock_id"] == ev["stock_id"]), None) or 0
        sold = self._sold.setdefault(oid, set())
        others = sorted(((pos["shares_owned"] * prices[sid], sid) for sid, pos in positions.items()
                         if pos.get("shares_owned") and prices.get(sid) and sid not in self._busy and sid not in sold),
                        reverse=True)
        if (snap.get("cash") or 0) >= avail * price * FUND_SPREAD or not others:
            self._funded.add(oid)
            return True
        sold.add(others[0][1])
        self._send(db, ev, "sell", 100, None, stock_id=others[0][1])
        return False

    # --------------------------------------------------------------------- step

    def step(self, db: Storage, s: EventSettings, live: bool, enabled: bool, now: int,
             prices: dict, positions: dict, snap: dict) -> None:
        """now = estimated server time (ms); prices = stock id -> latest price."""
        events = db.active_events(now)
        self._market = (prices, positions)
        self._busy = {ev["stock_id"] for ev in events if ev["phase"] not in FINAL}
        for ev in events:
            kind = ev["direction"]
            if kind not in ("pump", "crash") or ev["phase"] in FINAL:
                continue
            if ev["occurrence_id"] in self._pending:
                pass  # always finish a command already in flight
            elif not (enabled and live and switched_on(s, kind)):
                continue
            price = prices.get(ev["stock_id"])
            if price is None:
                continue
            pos = positions.get(ev["stock_id"]) or {}
            try:
                (self._pump if kind == "pump" else self._crash)(db, s, ev, now, price, pos, snap)
            except Exception:
                log.exception("event step failed")

    @staticmethod
    def _cooldown_free(snap: dict, action: str, now: int) -> bool:
        col = {"buy": "next_buy_ms", "short": "next_short_ms"}.get(action)
        return not col or (snap.get(col) or 0) <= now

    # --------------------------------------------------------------------- pump

    def _pump(self, db, s: EventSettings, ev: dict, now: int, price: float, pos: dict, snap: dict) -> None:
        phase, sched = ev["phase"], ev["scheduled_ms"]
        if phase.endswith("!"):
            res = self._result(db, ev)
            if res is None:
                return
            if phase == "buy!":
                self._set(db, ev, "hold" if res == "done" else "skipped")
            elif phase == "sell!":
                self._set(db, ev, "short_wait" if res == "done" and s.pump_short_pct else
                          "done" if res == "done" else "hold")
            elif phase == "short!":
                self._set(db, ev, "short_open" if res == "done" else "done", info=str(now))
            elif phase == "cover!":
                self._set(db, ev, "done" if res == "done" else "short_open")
            return

        if phase == "wait_buy":
            if now >= sched:
                self._set(db, ev, "skipped")
                self._log(db, ev, t("event.log.too_late"))
            elif s.fund_events and now < sched - PUMP_FUND_STOP_S * 1000 and not self._fund(db, ev, snap, price):
                return                      # first the cash: a pump multiplies the stake, the sell spread is ~2 %
            elif self._cooldown_free(snap, "buy", now):
                self._pending.pop(ev["occurrence_id"] + "#fund", None)    # an unanswered funding sell: buy anyway
                ev["start_price"] = price
                self._send(db, ev, "buy", s.pump_buy_pct, "buy!")
        elif phase == "hold":
            if not pos.get("shares_owned"):
                self._set(db, ev, "done")
                return
            start, target = ev["start_price"] or price, ev["target_price"]
            if s.pump_target_share and target > start and price >= start + (target - start) * s.pump_target_share / 100:
                # the target is announced: sell close to it instead of after the pullback from the peak
                self._log(db, ev, t("event.log.near_target", price=f"{price:.4g}", target=f"{target:.4g}"))
                self._send(db, ev, "sell", 100, "sell!")
                return
            if now < sched:
                return
            peak = max(ev["extreme"] or 0.0, price)
            if peak != ev["extreme"]:
                self._set(db, ev, "hold", extreme=peak)
            started = peak >= start + (target - start) * s.pump_start_share / 100
            if started and price <= peak * (1 - s.pump_drop_pct / 100):
                self._log(db, ev, t("event.log.peak_drop", peak=f"{peak:.4g}", price=f"{price:.4g}"))
                self._send(db, ev, "sell", 100, "sell!")
            elif now >= sched + s.pump_safety_s * 1000:
                self._log(db, ev, t("event.log.safety"))
                self._send(db, ev, "sell", 100, "sell!")
        elif phase == "short_wait":
            if now >= sched + s.pump_cover_max_s * 1000:
                self._set(db, ev, "done")
            elif self._cooldown_free(snap, "short", now):
                self._send(db, ev, "short", s.pump_short_pct, "short!")
        elif phase == "short_open":
            if not pos.get("shares_shorted"):
                self._set(db, ev, "done")
                return
            opened = int(ev["info"] or now)
            limit = (ev["start_price"] or price) * (1 + s.pump_cover_pct / 100)
            if price <= limit or now >= opened + s.pump_cover_max_s * 1000:
                self._send(db, ev, "cover", 100, "cover!")

    # -------------------------------------------------------------------- crash

    def _crash(self, db, s: EventSettings, ev: dict, now: int, price: float, pos: dict, snap: dict) -> None:
        phase, sched = ev["phase"], ev["scheduled_ms"]
        if phase.endswith("!"):
            res = self._result(db, ev)
            if res is None:
                return
            if phase == "sell!":
                self._set(db, ev, "short_wait" if s.crash_short_pct else "wait_crash")
            elif phase == "short!":
                self._set(db, ev, "wait_crash")
            elif phase == "cover!":
                self._set(db, ev, "rebuy_wait" if s.crash_rebuy_pct else "done")
            elif phase == "rebuy!":
                self._set(db, ev, "done" if res == "done" else "rebuy_wait")
            return

        pre_start = sched - s.crash_minutes * 60_000
        if (s.fund_events and s.crash_rebuy_pct and phase in ("short_wait", "wait_crash", "rebuy_wait")
                and now >= sched - CRASH_FUND_S * 1000):
            # the buy-back near the bottom is the big trade: give it all the cash (a sell per step, beside the phase)
            self._fund(db, ev, snap, ev["target_price"] or price)
        if phase == "wait_pre":
            if now >= sched:
                self._set(db, ev, "skipped")
                self._log(db, ev, t("event.log.too_late"))
            elif now >= pre_start:
                ev["start_price"] = price
                if pos.get("shares_owned"):
                    self._send(db, ev, "sell", 100, "sell!")
                else:
                    self._set(db, ev, "short_wait" if s.crash_short_pct else "wait_crash")
        elif phase == "short_wait":
            if now >= sched:
                self._set(db, ev, "wait_crash")
            elif self._cooldown_free(snap, "short", now):
                self._send(db, ev, "short", s.crash_short_pct, "short!")
        elif phase == "wait_crash":
            target = ev["target_price"]
            # the target is announced: act at the bottom instead of after the rebound (a price that low only
            # happens in the crash, so also when the server clock estimate is a moment behind)
            at_target = bool(s.crash_target_pct and target and target < (ev["start_price"] or price)
                             and price <= target * (1 + s.crash_target_pct / 100))
            if now < sched and not at_target:
                return
            low = min(ev["extreme"] or price, price)
            if low != ev["extreme"]:
                self._set(db, ev, "wait_crash", extreme=low)
            rise = price >= low * (1 + s.crash_rise_pct / 100)
            if at_target or rise or now >= sched + s.crash_safety_s * 1000:
                self._log(db, ev, t("event.log.near_target", price=f"{price:.4g}", target=f"{target:.4g}") if at_target
                          else t("event.log.low_rise", low=f"{low:.4g}", price=f"{price:.4g}") if rise
                          else t("event.log.safety"))
                if pos.get("shares_shorted"):
                    self._send(db, ev, "cover", 100, "cover!")
                else:
                    self._set(db, ev, "rebuy_wait" if s.crash_rebuy_pct else "done")
        elif phase == "rebuy_wait":
            if now >= sched + 10 * 60_000:
                self._set(db, ev, "done")       # give up re-buying after 10 minutes
            elif self._cooldown_free(snap, "buy", now):
                self._send(db, ev, "buy", s.crash_rebuy_pct, "rebuy!")
