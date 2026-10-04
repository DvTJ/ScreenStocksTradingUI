"""Rule engine: stop-loss, take-profit, trailing stop and limit orders.

Runs in its own thread, evaluates all enabled rules against the newest
market.json prices and fires trade commands through the mod's command files.
A rule is one-shot by default: after a successful execution it disables itself.
With "repeat" it stays enabled and re-arms once the price has left the trigger
zone again, so a limit buy below its limit does not fire on every tick.
"""

import json
import logging
import re
import threading
import time
from typing import Optional

from . import config
from .bot import BotTrader, load_settings as load_bot_settings
from .collector import Collector
from .commands import CommandWriter, action_name, reason_text, status_text, ACTIONS
from .events import FINAL as EVENT_FINAL, EventTrader, load_settings as load_event_settings
from .i18n import keys as text_keys, t, variants
from .storage import Storage

log = logging.getLogger(__name__)

KIND_KEYS = ("stop_loss", "take_profit", "trailing_stop", "buy_limit", "short_limit")
SIDE_KEYS = ("long", "short")
MODE_KEYS = ("price", "pct")

# Exit rules act on an existing position; limit rules open one.
EXIT_KINDS = ("stop_loss", "take_profit", "trailing_stop")

# Rejections worth retrying instead of giving up on the rule.
RETRY_REASONS = {"cooldown", "rate-limited", "queue-full", "not-ready", "held"}

RESULT_TIMEOUT_S = 8.0
RETRY_BACKOFF_S = 3.0


def kind_name(kind: str) -> str:
    return t(f"kind.{kind}", default=kind)


def side_name(side: str) -> str:
    return t(f"side.{side}", default=side)


def mode_name(mode: str) -> str:
    return t(f"mode.{mode}", default=mode)


def rule_action(rule: dict) -> str:
    if rule["kind"] in EXIT_KINDS:
        return "sell" if rule["side"] == "long" else "cover"
    return "buy" if rule["kind"] == "buy_limit" else "short"


def needs_position(rule: dict) -> bool:
    return rule["kind"] in EXIT_KINDS


def has_position(rule: dict, pos: Optional[dict]) -> bool:
    if not pos:
        return False
    return bool(pos["shares_owned"] if rule["side"] == "long" else pos["shares_shorted"])


def trigger_price(rule: dict, pos: Optional[dict]) -> Optional[float]:
    kind, side, v = rule["kind"], rule["side"], rule["value"]
    long_ = side == "long"
    if kind in ("buy_limit", "short_limit"):
        return v
    if kind == "trailing_stop":
        ext = rule.get("extreme")
        if not ext:
            return None
        return ext * (1 - v / 100) if long_ else ext * (1 + v / 100)
    if rule["mode"] == "price":
        return v
    ref = (pos or {}).get("avg_buy_price" if long_ else "avg_short_price")
    if not ref:
        return None
    if kind == "stop_loss":
        return ref * (1 - v / 100) if long_ else ref * (1 + v / 100)
    return ref * (1 + v / 100) if long_ else ref * (1 - v / 100)  # take_profit


def triggers_below(rule: dict) -> bool:
    """True if the rule fires when the price falls to/below the trigger."""
    kind, long_ = rule["kind"], rule["side"] == "long"
    if kind == "buy_limit":
        return True
    if kind == "short_limit":
        return False
    if kind == "take_profit":
        return not long_
    return long_  # stop-loss / trailing stop


def condition_met(rule: dict, price: float, trig: float) -> bool:
    return price <= trig if triggers_below(rule) else price >= trig


def describe_trigger(rule: dict, trig: Optional[float], fmt_price, decimal_sep: str = ".") -> str:
    op = "≤" if triggers_below(rule) else "≥"
    v = f"{rule['value']:g}".replace(".", decimal_sep)
    suffix = f" ({op} {fmt_price(trig)})" if trig else ""
    if rule["kind"] == "trailing_stop":
        base = t("trigger.trail_high") if rule["side"] == "long" else t("trigger.trail_low")
        return t("trigger.trail", v=v, base=base) + suffix
    if rule["kind"] in EXIT_KINDS and rule["mode"] == "pct":
        sign = "−" if (rule["kind"] == "stop_loss") == (rule["side"] == "long") else "+"
        return t("trigger.entry", sign=sign, v=v) + suffix
    return f"{op} {fmt_price(trig if trig is not None else rule['value'])}"


# ---------------------------------------------------------------- rule status
# The status is stored as key + raw values ({"k": "rule.st.…", "v": {...}}) and translated when it is
# shown, so it follows the current language. Reason/status codes of the game are translated, too.
_STATUS_CONVERT = {"reason": reason_text, "status": status_text}


def status_msg(key: str, **values) -> str:
    return json.dumps({"k": key, "v": {k: str(v) for k, v in values.items()}}, ensure_ascii=False)


def status_display(raw: Optional[str]) -> str:
    """Stored rule status -> text in the current language (older plain texts are shown as they are)."""
    if not raw or not raw.startswith('{"k"'):
        return raw or ""
    try:
        data = json.loads(raw)
        values = {k: _STATUS_CONVERT[k](v) if k in _STATUS_CONVERT else v for k, v in data.get("v", {}).items()}
        return t(data["k"], **values)
    except (ValueError, KeyError, TypeError):
        return raw


def _status_patterns() -> list[tuple[str, re.Pattern]]:
    """Regexes for the German and English status texts, most specific (longest literal text) first."""
    out = []
    for key in text_keys():
        if not key.startswith("rule.st."):
            continue
        for text in variants(key):
            parts = re.split(r"\{(\w+)\}", text)
            rx = "".join(re.escape(p) if i % 2 == 0 else f"(?P<{p}>.+?)" for i, p in enumerate(parts))
            literal = sum(len(p) for p in parts[::2])
            out.append((literal, key, re.compile(f"^{rx}$", re.S)))
    return [(key, rx) for _, key, rx in sorted(out, key=lambda x: -x[0])]


def migrate_status_texts(db: Storage) -> int:
    """Convert statuses stored as translated text (before 2.0) into key + values. Returns the count."""
    patterns, changed = _status_patterns(), 0
    # translated game codes back to the codes ("Kein Volumen verfügbar" -> "no-volume")
    codes = {"status": {}, "reason": {}}
    for key in text_keys():
        for name, prefix in (("status", "cmdstatus."), ("reason", "reason.")):
            if key.startswith(prefix):
                for text in variants(key):
                    codes[name][text] = key[len(prefix):]
    for rule in db.rules():
        raw = rule.get("status")
        if not raw or raw.startswith('{"k"'):
            continue
        for key, rx in patterns:
            m = rx.match(raw)
            if m:
                values = {k: codes.get(k, {}).get(v, v) for k, v in m.groupdict().items()}
                db.update_rule(rule["id"], status=status_msg(key, **values))
                changed += 1
                break
    return changed


class AutomationEngine(threading.Thread):
    INTERVAL_S = 0.25

    def __init__(self, collector: Collector, db_path, writer: CommandWriter):
        super().__init__(name="automation", daemon=True)
        self.collector = collector
        self.db_path = db_path
        self.writer = writer
        self._stop_event = threading.Event()
        self._since: dict[int, float] = {}          # rule id -> local time condition became true
        self._pending: dict[int, tuple] = {}        # rule id -> (SentCommand, known ids, local send time)
        self._retry_at: dict[int, float] = {}
        self._status: dict[int, str] = {}
        self._rearm: set[int] = set()               # repeat rules waiting for the price to leave the trigger zone
        self._seen: set[int] = set()
        self.state = "starting"                     # starting / active / paused / not_live
        self.events = EventTrader(writer)           # announced pumps / crashes (events.py)
        self.bot = BotTrader(writer)                # mean-reversion bot (bot.py)

    def stop(self) -> None:
        self._stop_event.set()

    def armed_ids(self) -> set[int]:
        """Rules whose condition is currently met or whose command is in flight."""
        return set(self._since) | set(self._pending)

    def run(self) -> None:
        db = Storage(self.db_path)
        try:
            try:
                n = migrate_status_texts(db)
                if n:
                    log.info("converted %d rule statuses to translatable form", n)
            except Exception:
                log.exception("rule status migration failed")
            while not self._stop_event.is_set():
                try:
                    self._step(db)
                except Exception:
                    log.exception("automation error")
                self._stop_event.wait(self.INTERVAL_S)
        finally:
            db.close()

    # ------------------------------------------------------------------ helpers

    def _set_status(self, db: Storage, rule: dict, status: str) -> None:
        if self._status.get(rule["id"]) != status:
            self._status[rule["id"]] = status
            db.update_rule(rule["id"], status=status)

    def _log(self, db: Storage, rule: Optional[dict], msg: str) -> None:
        log.info("rule %s: %s", rule["id"] if rule else "-", msg)
        db.log_rule(int(time.time() * 1000), rule["id"] if rule else None,
                    rule["stock_id"] if rule else "", msg)

    # --------------------------------------------------------------------- step

    def _step(self, db: Storage) -> None:
        enabled = db.get_setting("automation_enabled", "1") == "1"
        st = self.collector.status.copy()
        live = bool(st.last_market_read) and time.time() - st.last_market_read < config.STALE_AFTER_MS / 1000
        self.state = "active" if enabled and live else "paused" if not enabled else "not_live"

        rules = db.rules(enabled_only=True)
        active_ids = {r["id"] for r in rules}
        for d in (self._since, self._pending, self._retry_at, self._status):
            for rid in list(d):
                if rid not in active_ids:
                    if d is self._pending:
                        self.writer.cancel(d[rid][0])
                    d.pop(rid)
        self._rearm &= active_ids
        self._seen &= active_ids

        prices = {s["stock_id"]: s["last_price"] for s in db.stocks()}
        positions = db.current_positions()
        snap = db.latest_snapshot() or {}
        server_now = (snap.get("server_ms") or 0) + int((time.time() - (st.last_market_read or time.time())) * 1000)
        now = time.time()

        self.events.step(db, load_event_settings(db), live, enabled, server_now, prices, positions, snap)
        event_ids = {ev["stock_id"] for ev in db.active_events(server_now) if ev["phase"] not in EVENT_FINAL}
        self.bot.step(db, load_bot_settings(db), live, enabled, now, server_now,
                      {s["stock_id"]: s for s in db.stocks()}, positions, snap, event_ids)
        if not rules:
            return

        for rule in rules:
            rid, sid = rule["id"], rule["stock_id"]
            price, pos = prices.get(sid), positions.get(sid)

            # trailing stop follows the best price while the position is open
            if rule["kind"] == "trailing_stop":
                if has_position(rule, pos) and price:
                    ext = rule["extreme"]
                    better = ext is None or (price > ext if rule["side"] == "long" else price < ext)
                    if better:
                        rule["extreme"] = price
                        db.update_rule(rid, extreme=price)
                elif rule["extreme"] is not None and rid not in self._pending:
                    rule["extreme"] = None
                    db.update_rule(rid, extreme=None)

            if rid in self._pending:
                self._check_pending(db, rule)
                continue
            if rid not in self._seen:
                self._seen.add(rid)
                if rule["repeat"] and rule["runs"]:
                    # after a restart, an already executed repeat rule waits for a fresh crossing
                    self._rearm.add(rid)
            if not enabled or not live or price is None:
                self._since.pop(rid, None)
                continue
            if needs_position(rule) and not has_position(rule, pos):
                self._since.pop(rid, None)
                self._set_status(db, rule, status_msg("rule.st.wait_position"))
                continue
            trig = trigger_price(rule, pos)
            if trig is None:
                self._set_status(db, rule, status_msg("rule.st.wait_reference"))
                continue
            met = condition_met(rule, price, trig)
            if rid in self._rearm:
                if met:
                    self._set_status(db, rule, status_msg("rule.st.rearm", n=rule["runs"]))
                    continue
                self._rearm.discard(rid)
                self._log(db, rule, t("rule.log.rearmed"))
            if not met:
                self._since.pop(rid, None)
                self._set_status(db, rule, status_msg("rule.st.active"))
                continue

            since = self._since.setdefault(rid, now)
            if now - since < rule["confirm_s"]:
                self._set_status(db, rule, status_msg("rule.st.confirming", n=f"{now - since:.0f}",
                                                      total=f"{rule['confirm_s']:g}"))
                continue
            if self._retry_at.get(rid, 0) > now:
                continue
            action = rule_action(rule)
            cd_col = {"buy": "next_buy_ms", "short": "next_short_ms"}.get(action)
            if cd_col and (snap.get(cd_col) or 0) > server_now:
                self._set_status(db, rule, status_msg("rule.st.wait_buy_cd" if action == "buy" else "rule.st.wait_short_cd"))
                continue
            self._fire(db, rule, action, price, trig)

    def _fire(self, db: Storage, rule: dict, action: str, price: float, trig: float) -> None:
        known = {r["id"] for r in db.command_results(200)}
        try:
            sent = self.writer.send(rule["stock_id"], action, rule["percent"])
        except Exception as exc:
            self._retry_at[rule["id"]] = time.time() + 10
            self._set_status(db, rule, status_msg("rule.st.send_error", error=exc))
            self._log(db, rule, t("rule.log.send_failed", error=exc))
            return
        self._pending[rule["id"]] = (sent, known, time.time())
        db.update_rule(rule["id"], triggered_ms=int(time.time() * 1000))
        self._set_status(db, rule, status_msg("rule.st.triggered"))
        self._log(db, rule, t("rule.log.triggered", kind=kind_name(rule["kind"]), price=f"{price:.4g}",
                              op="≤" if triggers_below(rule) else "≥", trigger=f"{trig:.4g}",
                              action=action_name(action), p=sent.percent))

    def _check_pending(self, db: Storage, rule: dict) -> None:
        sent, known, t_sent = self._pending[rule["id"]]
        prefix = ACTIONS[sent.action]
        new = [r for r in db.command_results(50)
               if r["id"] not in known and r["stock_id"] == sent.stock_id and (r["action"] or "").startswith(prefix)]
        if new:
            res = new[0]
            status, reason = res["status"], res["reason"] or ""
            if status == "done":
                self._pending.pop(rule["id"])
                runs = (rule["runs"] or 0) + 1
                rule["runs"] = runs
                self._log(db, rule, t("rule.log.done", action=action_name(sent.action), p=sent.percent)
                          + (f" ({runs}×)" if rule["repeat"] else ""))
                if rule["repeat"]:
                    db.update_rule(rule["id"], runs=runs, extreme=None)
                    rule["extreme"] = None
                    self._since.pop(rule["id"], None)
                    self._rearm.add(rule["id"])
                    self._set_status(db, rule, status_msg("rule.st.rearm", n=runs))
                else:
                    db.update_rule(rule["id"], enabled=0, runs=runs)
                    self._set_status(db, rule, status_msg("rule.st.done"))
            elif status in ("rejected", "failed"):
                self._pending.pop(rule["id"])
                if reason in RETRY_REASONS:
                    self._retry_at[rule["id"]] = time.time() + RETRY_BACKOFF_S
                    self._set_status(db, rule, status_msg("rule.st.waiting_reason", reason=reason))
                    self._log(db, rule, t("rule.log.retry", status=status_text(status), reason=reason_text(reason)))
                elif rule["repeat"]:
                    # keep a repeating rule alive; it fires again on the next crossing
                    self._since.pop(rule["id"], None)
                    self._rearm.add(rule["id"])
                    self._set_status(db, rule, status_msg("rule.st.rejected_rearm", status=status, reason=reason))
                    self._log(db, rule, t("rule.log.rejected_rearm", status=status_text(status),
                                          reason=reason_text(reason)))
                else:
                    db.update_rule(rule["id"], enabled=0)
                    self._set_status(db, rule, status_msg("rule.st.final", status=status, reason=reason))
                    self._log(db, rule, t("rule.log.disabled", status=status_text(status),
                                          reason=reason_text(reason)))
            return
        if time.time() - t_sent > RESULT_TIMEOUT_S:
            self._pending.pop(rule["id"])
            self.writer.cancel(sent)
            self._retry_at[rule["id"]] = time.time() + 10
            self._set_status(db, rule, status_msg("rule.st.no_response"))
            self._log(db, rule, t("rule.log.no_response"))
