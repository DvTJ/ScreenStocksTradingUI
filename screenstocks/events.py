"""Trading on events the game announces in advance (scheduledNews: "pump" / "crash").

Observed in the data:
  pump  - announced ~1 min before; at the scheduled second the price spikes to
          roughly the target (e.g. 9 -> 109 within 1 s) and falls back within ~45 s.
  crash - announced hours before; the price drifts down in the last minutes,
          drops to roughly the target for a few seconds and recovers within ~30 min.

Pump:  buy after the announcement -> from the scheduled time follow the peak and
       sell once the price is X % below it (only after the pump really started;
       emergency sell N s after the scheduled time) -> short -> cover when the price
       is back near the pre-pump level (or after a maximum time).
Crash: N minutes before: sell the long position and open a short -> from the
       scheduled time follow the low and, once the price rises X % from it, cover
       the short and buy back (emergency N s after the scheduled time).

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


@dataclass
class EventSettings:
    pumps: bool = False
    crashes: bool = False
    pump_buy_pct: int = 100
    pump_drop_pct: float = 10.0       # sell when the price is this far below the peak
    pump_start_share: float = 50.0    # the pump counts as started at this share of the way to the target
    pump_safety_s: int = 30           # sell at the latest this long after the scheduled time
    pump_short_pct: int = 100         # 0 = no short after the pump
    pump_cover_pct: float = 20.0      # cover when price <= pre-pump price * (1 + x %)
    pump_cover_max_s: int = 120       # cover at the latest this long after shorting
    crash_minutes: int = 15           # sell + short this long before the crash
    crash_short_pct: int = 100        # 0 = only sell
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


class EventTrader:
    def __init__(self, writer: CommandWriter):
        self.writer = writer
        self._pending: dict[str, tuple] = {}   # occurrence id -> (SentCommand, known ids, local send time)

    # ------------------------------------------------------------------ helpers

    def _log(self, db: Storage, ev: dict, msg: str) -> None:
        log.info("event %s %s: %s", ev["stock_id"], ev["direction"], msg)
        db.log_rule(int(time.time() * 1000), None, ev["stock_id"],
                    f"{t('event.' + ev['direction'])} {ev['stock_id']}: {msg}")

    def _set(self, db: Storage, ev: dict, phase: str, **fields) -> None:
        ev.update(phase=phase, **fields)
        db.save_event_state(ev)

    def _send(self, db: Storage, ev: dict, action: str, pct: int, next_phase: str) -> bool:
        known = {r["id"] for r in db.command_results(200)}
        try:
            sent = self.writer.send(ev["stock_id"], action, pct)
        except Exception as exc:
            self._log(db, ev, t("rule.log.send_failed", error=exc))
            return False
        self._pending[ev["occurrence_id"]] = (sent, known, time.time())
        self._set(db, ev, next_phase)
        self._log(db, ev, t("event.log.sent", action=action_name(action), p=sent.percent))
        return True

    def _result(self, db: Storage, ev: dict) -> Optional[str]:
        """'done' / 'rejected' / 'timeout' once the game answered the pending command, else None."""
        sent, known, t_sent = self._pending[ev["occurrence_id"]]
        prefix = ACTIONS[sent.action]
        new = [r for r in db.command_results(50)
               if r["id"] not in known and r["stock_id"] == sent.stock_id and (r["action"] or "").startswith(prefix)]
        if new and new[0]["status"] in ("done", "rejected", "failed"):
            res = new[0]
            del self._pending[ev["occurrence_id"]]
            if res["status"] == "done":
                self._log(db, ev, t("rule.log.done", action=action_name(sent.action), p=sent.percent))
                return "done"
            self._log(db, ev, t("event.log.rejected", status=status_text(res["status"]),
                                reason=reason_text(res["reason"])))
            return "rejected"
        if time.time() - t_sent > RESULT_TIMEOUT_S:
            del self._pending[ev["occurrence_id"]]
            self.writer.cancel(sent)
            self._log(db, ev, t("rule.log.no_response"))
            return "timeout"
        return None

    # --------------------------------------------------------------------- step

    def step(self, db: Storage, s: EventSettings, live: bool, enabled: bool, now: int,
             prices: dict, positions: dict, snap: dict) -> None:
        """now = estimated server time (ms); prices = stock id -> latest price."""
        for ev in db.active_events(now):
            kind = ev["direction"]
            if kind not in ("pump", "crash") or ev["phase"] in FINAL:
                continue
            switched_on = s.pumps if kind == "pump" else s.crashes
            if ev["occurrence_id"] in self._pending:
                pass  # always finish a command already in flight
            elif not (enabled and live and switched_on):
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
            elif self._cooldown_free(snap, "buy", now):
                ev["start_price"] = price
                self._send(db, ev, "buy", s.pump_buy_pct, "buy!")
        elif phase == "hold":
            if not pos.get("shares_owned"):
                self._set(db, ev, "done")
                return
            if now < sched:
                return
            start, target = ev["start_price"] or price, ev["target_price"]
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
            if now < sched:
                return
            low = min(ev["extreme"] or price, price)
            if low != ev["extreme"]:
                self._set(db, ev, "wait_crash", extreme=low)
            rise = price >= low * (1 + s.crash_rise_pct / 100)
            if rise or now >= sched + s.crash_safety_s * 1000:
                self._log(db, ev, t("event.log.low_rise", low=f"{low:.4g}", price=f"{price:.4g}") if rise
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
