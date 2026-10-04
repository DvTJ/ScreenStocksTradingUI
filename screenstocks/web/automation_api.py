"""Automation tab of the web UI: master switch, rules, announced-event trading and log.

Mixed into Bridge (bridge.py). Validation, storage and logging follow the classic
AutomationTab exactly; the engine itself (automation.py / events.py) is unchanged.
"""

import time
from dataclasses import asdict, fields
from typing import Optional

import webview

from .. import config_io
from ..automation import (EXIT_KINDS, KIND_KEYS, MODE_KEYS, SIDE_KEYS, condition_met, describe_trigger,
                          has_position, kind_name, mode_name, needs_position, side_name, status_display,
                          status_msg, trigger_price)
from ..commands import normalize_percent
from ..events import EventSettings, load_settings as load_event_settings, save_settings as save_event_settings
from ..gui import fmt as pyfmt
from ..i18n import t

PUMP_PARAMS = ("pump_buy_pct", "pump_drop_pct", "pump_start_share", "pump_safety_s", "pump_short_pct",
               "pump_cover_pct", "pump_cover_max_s")
CRASH_PARAMS = ("crash_minutes", "crash_short_pct", "crash_rise_pct", "crash_safety_s", "crash_rebuy_pct")


def _num(value) -> float:
    return float(str(value).strip().replace(",", "."))


class AutomationApi:
    # ------------------------------------------------------------------ helpers

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _parse_rule(self, form: dict) -> tuple[Optional[dict], str]:
        """Form -> rule dict (same rules as the classic form). Returns (rule, error text)."""
        try:
            value = _num(form.get("value"))
            pct = normalize_percent(_num(form.get("percent")))
            confirm = max(0.0, _num(form.get("confirm_s") or 0))
        except (TypeError, ValueError):
            return None, t("auto.invalid_form")
        kind = form.get("kind") if form.get("kind") in KIND_KEYS else None
        side = form.get("side") if form.get("side") in SIDE_KEYS else "long"
        if not kind or not form.get("stock_id"):
            return None, t("auto.invalid_form")
        mode = ("price" if kind in ("buy_limit", "short_limit") else
                "pct" if kind == "trailing_stop" else
                form.get("mode") if form.get("mode") in MODE_KEYS else "pct")
        rule = dict(id=0, stock_id=str(form["stock_id"]), kind=kind, side=side, mode=mode, value=value, percent=pct,
                    confirm_s=confirm, extreme=None, repeat=int(bool(form.get("repeat"))), runs=0)
        if value <= 0 or (mode == "pct" and value >= 100 and kind != "take_profit"):
            return None, t("auto.invalid_value")
        return rule, ""

    def _context(self, stock_id: str) -> tuple[Optional[tuple], Optional[dict]]:
        last = self._db.latest_price(stock_id)
        pos = self._db.current_positions().get(stock_id)
        return last, pos

    # --------------------------------------------------------------------- read

    def automation(self) -> dict:
        """Everything the tab shows (called every second while it is open)."""
        if self._closing:
            return {}
        with self._lock:
            db = self._db
            master = db.get_setting("automation_enabled", "1") == "1"
            positions = db.current_positions()
            stocks = db.stock_ids()
            prices = {sid: db.latest_price(sid) for sid in stocks}
            armed = self._engine.armed_ids()
            rules = []
            for r in db.rules():
                pos = positions.get(r["stock_id"])
                last = prices.get(r["stock_id"])
                price = last[1] if last else None
                trig = trigger_price(r, pos)
                rules.append(dict(
                    id=r["id"], stock=r["stock_id"], kind=r["kind"], kind_text=kind_name(r["kind"]),
                    side=r["side"], side_text=side_name(r["side"]) if r["kind"] in EXIT_KINDS else "",
                    mode=r["mode"], value=r["value"], percent=r["percent"], confirm_s=r["confirm_s"],
                    repeat=bool(r["repeat"]), runs=r["runs"] or 0, enabled=bool(r["enabled"]),
                    trigger_text=describe_trigger(r, trig, pyfmt.price, pyfmt.decimal_sep()), trigger=trig,
                    price=price, distance=(trig / price - 1) * 100 if trig and price else None,
                    status=status_display(r["status"]), armed=r["id"] in armed))
            ev_settings = load_event_settings(db)
            snap = db.latest_snapshot() or {}
            now = snap.get("server_ms") or self._now_ms()
            events = []
            for ev in db.recent_events(50):
                on = ev_settings.pumps if ev["direction"] == "pump" else ev_settings.crashes
                phase = ev["phase"]
                future = ev["scheduled_ms"] >= now
                if phase is None or (not on and phase in ("wait_buy", "wait_pre")):
                    phase_text = t("event.off") if future and not on else "–"
                else:
                    phase_text = t(f"event.phase.{phase}", default=phase)
                events.append(dict(id=ev["occurrence_id"], stock=ev["stock_id"], direction=ev["direction"],
                                   direction_text=t(f"event.{ev['direction']}", default=ev["direction"]),
                                   target=ev["target_price"], at=ev["scheduled_ms"], future=future,
                                   phase=phase, phase_text=phase_text))
            log = [dict(id=lid, time=ts, rule=rid, stock=sid, msg=msg) for lid, ts, rid, sid, msg in db.rule_log(300)]
        return {"master": master, "engine": self._engine.state, "rules": rules, "events": events,
                "event_settings": asdict(ev_settings), "log": log, "stocks": stocks, "now": now,
                "prices": {sid: (p[1] if p else None) for sid, p in prices.items()},
                "kinds": {k: kind_name(k) for k in KIND_KEYS}, "sides": {k: side_name(k) for k in SIDE_KEYS},
                "modes": {**{k: mode_name(k) for k in MODE_KEYS}, "trail": t("mode.trail")},
                "exit_kinds": list(EXIT_KINDS)}

    def rule_preview(self, form: dict) -> dict:
        """Help text below the form and whether the rule would fire right away."""
        kind = form.get("kind") if form.get("kind") in KIND_KEYS else "stop_loss"
        side = form.get("side") if form.get("side") in SIDE_KEYS else "long"
        below = {"stop_loss": side == "long", "take_profit": side != "long"}.get(kind, True)
        lines = [t(f"auto.help.{kind}", pct=form.get("percent") or "?", side=side_name(side),
                   dir=t("auto.dir_below") if below else t("auto.dir_above"))]
        would_fire, price = False, None
        rule, _err = self._parse_rule(form)
        if rule:
            with self._lock:
                last, pos = self._context(rule["stock_id"])
            price = last[1] if last else None
            probe = dict(rule, extreme=price if kind == "trailing_stop" else None)
            trig = trigger_price(probe, pos)
            extra = [t("auto.current_trigger", trigger=describe_trigger(probe, trig, pyfmt.price, pyfmt.decimal_sep()))]
            if price is not None:
                extra.append(t("auto.current_price", price=pyfmt.price(price)))
            if needs_position(rule) and not has_position(rule, pos):
                extra.append(t("auto.no_position", side=side_name(side), stock=rule["stock_id"]))
            lines.append("   ·   ".join(extra))
            would_fire = bool(price and trig and condition_met(probe, price, trig)
                              and (not needs_position(rule) or has_position(rule, pos)))
        lines.append(t("auto.repeat_on_help") if form.get("repeat") else t("auto.repeat_off_help"))
        return {"help": lines, "would_fire": would_fire,
                "would_fire_text": t("auto.would_fire", price=pyfmt.price(price)) if would_fire else ""}

    def rule_form(self, rule_id: int) -> Optional[dict]:
        """Values of an existing rule for the edit form."""
        with self._lock:
            r = next((r for r in self._db.rules() if r["id"] == int(rule_id)), None)
        if not r:
            return None
        return dict(id=r["id"], stock_id=r["stock_id"], kind=r["kind"], side=r["side"], mode=r["mode"],
                    value=f"{r['value']:g}".replace(".", pyfmt.decimal_sep()), percent=r["percent"],
                    confirm_s=f"{r['confirm_s']:g}", repeat=bool(r["repeat"]))

    # -------------------------------------------------------------------- write

    def save_rule(self, form: dict, edit_id: Optional[int] = None) -> dict:
        """Create a rule or, with edit_id, update it. Returns {"ok", "text"}."""
        rule, err = self._parse_rule(form)
        if not rule:
            return {"ok": False, "text": err}
        trigger = describe_trigger(rule, None, pyfmt.price, pyfmt.decimal_sep())
        with self._lock:
            db = self._db
            if edit_id:
                rid = int(edit_id)
                db.update_rule(rid, stock_id=rule["stock_id"], kind=rule["kind"], side=rule["side"], mode=rule["mode"],
                               value=rule["value"], percent=rule["percent"], confirm_s=rule["confirm_s"],
                               repeat=rule["repeat"], extreme=None, status=status_msg("rule.st.active"))
                db.log_rule(self._now_ms(), rid, rule["stock_id"],
                            t("rule.log.edited", kind=kind_name(rule["kind"]), trigger=trigger, p=rule["percent"],
                              rep=" ↻" if rule["repeat"] else ""))
                return {"ok": True, "text": t("web.auto.saved", id=rid)}
            rid = db.add_rule(rule["stock_id"], rule["kind"], rule["side"], rule["mode"], rule["value"],
                              rule["percent"], rule["confirm_s"], self._now_ms(),
                              repeat=bool(rule["repeat"]), status=status_msg("rule.st.active"))
            db.log_rule(self._now_ms(), rid, rule["stock_id"],
                        t("rule.log.created", kind=kind_name(rule["kind"]),
                          side=side_name(rule["side"]) if rule["kind"] in EXIT_KINDS else "",
                          trigger=trigger, p=rule["percent"]) + (" ↻" if rule["repeat"] else ""))
        return {"ok": True, "text": t("web.auto.created", id=rid)}

    def _rule(self, rule_id: int) -> Optional[dict]:
        return next((r for r in self._db.rules() if r["id"] == int(rule_id)), None)

    def toggle_rule(self, rule_id: int) -> None:
        with self._lock:
            r = self._rule(rule_id)
            if not r:
                return
            on = not r["enabled"]
            self._db.update_rule(r["id"], enabled=int(on), status=status_msg("rule.st.active") if on else status_msg("rule.st.disabled"),
                                 **({"extreme": None} if on else {}))
            self._db.log_rule(self._now_ms(), r["id"], r["stock_id"],
                              t("rule.log.enabled") if on else t("rule.log.disabled_manual"))

    def toggle_repeat(self, rule_id: int) -> None:
        with self._lock:
            r = self._rule(rule_id)
            if not r:
                return
            on = not r["repeat"]
            self._db.update_rule(r["id"], repeat=int(on))
            self._db.log_rule(self._now_ms(), r["id"], r["stock_id"],
                              t("rule.log.repeat_on") if on else t("rule.log.repeat_off"))

    def delete_rule(self, rule_id: int) -> None:
        with self._lock:
            r = self._rule(rule_id)
            if not r:
                return
            self._db.delete_rule(r["id"])
            self._db.log_rule(self._now_ms(), r["id"], "", t("rule.log.deleted"))

    def set_master(self, on: bool) -> None:
        with self._lock:
            self._db.set_setting("automation_enabled", "1" if on else "0")
            self._db.log_rule(self._now_ms(), None, "", t("rule.log.master_on") if on else t("rule.log.master_off"))

    def save_events(self, values: dict) -> dict:
        """Store switches and parameters; invalid numbers keep their previous value (like the classic tab)."""
        with self._lock:
            old = load_event_settings(self._db)
            new_values = {"pumps": bool(values.get("pumps", old.pumps)),
                          "crashes": bool(values.get("crashes", old.crashes))}
            for f in fields(EventSettings):
                if f.name in ("pumps", "crashes"):
                    continue
                current = getattr(old, f.name)
                try:
                    v = _num(values.get(f.name, current))
                    if v < 0:
                        raise ValueError
                    new_values[f.name] = int(v) if isinstance(current, int) else v
                except (TypeError, ValueError):
                    new_values[f.name] = current
            new = EventSettings(**new_values)
            if new != old:
                save_event_settings(self._db, new)
                for k in ("pumps", "crashes"):
                    if getattr(new, k) != getattr(old, k):
                        self._db.log_rule(self._now_ms(), None, "",
                                          f"{t('event.switch_' + k)}: "
                                          f"{t('auto.col_active') if getattr(new, k) else t('event.off')}")
        return asdict(new)

    # ------------------------------------------------------- config export / import

    def config_export(self, rule_ids: list, with_events: bool) -> dict:
        """Chosen rules and/or the pump/crash settings to a JSON file (config_io, as in the classic tab)."""
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename="screenstocks-automation.json",
                                                 file_types=("JSON (*.json)",))
        if not result:
            return {"cancelled": True}
        path = str(result[0] if isinstance(result, (tuple, list)) else result)
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with self._lock:
                config_io.save_file(self._db, path, rule_ids={int(i) for i in rule_ids}, with_events=bool(with_events))
        except OSError as exc:
            return {"error": t("common.error", error=exc)}
        return {"message": t("config.exported", path=path)}

    def config_import(self) -> dict:
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("JSON (*.json)",))
        if not result:
            return {"cancelled": True}
        path = str(result[0] if isinstance(result, (tuple, list)) else result)
        try:
            with self._lock:
                added = config_io.load_file(self._db, path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"error": t("config.invalid", error=exc)}
        return {"message": t("config.imported", n=added)}
