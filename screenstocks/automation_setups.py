"""Switch saved bot settings and native game Auto Actions together."""

import json
import logging
import math
import re
import threading
import time
from dataclasses import asdict
from pathlib import Path

from . import bot, game_bridge, settings
from .storage import Storage

log = logging.getLogger(__name__)
CONFIG = "automation_setups"
STATE = "automation_setups_state"
MANUAL = "automation_setups_manual"
ACTION_FIELDS = ("stockId", "actionType", "condition", "targetPrice", "amountPercentage")
CHECK_SECONDS = 3
SUFFIXES = {"": 0, "k": 3, "m": 6, "b": 9, "t": 12, "qa": 15, "qi": 18,
            "sx": 21, "sp": 24, "oc": 27, "no": 30, "dc": 33}


def threshold(value):
    match = re.fullmatch(r"\s*(\+?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)\s*([a-z]*)\s*",
                         str(value), re.IGNORECASE)
    if not match or match[2].lower() not in SUFFIXES:
        raise ValueError("Invalid threshold")
    amount = float(match[1]) * 10 ** SUFFIXES[match[2].lower()]
    if not math.isfinite(amount):
        raise ValueError("Threshold is too large")
    return amount


def load(db, key, fallback):
    return json.loads(db.get_setting(key, json.dumps(fallback)))


def save(db, key, value):
    db.set_setting(key, json.dumps(value))


def config(db):
    return load(db, CONFIG, {"enabled": False, "switch_back": True, "metric": "net_worth", "profiles": {}})


def client():
    chosen = settings.load().game_dir
    path = Path(chosen) if chosen and game_bridge.is_game_dir(Path(chosen)) else game_bridge.find_game_dir()
    if path is None:
        raise game_bridge.BridgeError("no_game", "Game folder was not found")
    return game_bridge.Client(path)


def action_config(action):
    return {key: action[key] for key in ACTION_FIELDS}


def capture_actions():
    connection = client()
    try:
        state = connection.request("auto_actions.snapshot")
        if not state["unlocked"]:
            raise game_bridge.BridgeError("auto_actions_locked", "Auto Actions are locked")
        return {"active": state["active"],
                "actions": [{**action_config(a), "enabled": a["enabled"]} for a in state["actions"]]}
    finally:
        connection.close()


def apply_actions(connection, setup):
    state = connection.request("auto_actions.snapshot")
    if not state["unlocked"]:
        raise game_bridge.BridgeError("auto_actions_locked", "Auto Actions are locked")
    wanted = setup["actions"]
    if len(wanted) > state["slotLimit"]:
        raise game_bridge.BridgeError("no_free_slot", "This setup needs more Auto Actions slots")
    current = sorted(state["actions"], key=lambda a: a["slotIndex"])
    # Match identical configurations first so matching slots keep their cooldowns.
    remaining = list(current)
    matches = []
    for desired in wanted:
        match = next((a for a in remaining if action_config(a) == action_config(desired)), None)
        if match is not None:
            remaining.remove(match)
        matches.append((desired, match))
    needs_edits = any(a is None or a["enabled"] != d["enabled"] for d, a in matches)
    if not needs_edits and not any(a["enabled"] for a in remaining):
        if state["active"] != setup["active"]:
            connection.request("auto_actions.set_active", {"active": setup["active"]})
        return
    if state["active"]:
        connection.request("auto_actions.set_active", {"active": False})
    for desired, original in matches:
        if original is None and remaining:
            original = remaining.pop(0)
        payload = action_config(desired)
        if original is None:
            result = connection.request("auto_actions.add", payload)
            slot = result["slotIndex"]
        else:
            slot = original["slotIndex"]
            if action_config(original) != payload:
                connection.request("auto_actions.update", {**payload, "slotIndex": slot})
        if original is None or original["enabled"] != desired["enabled"]:
            connection.request("auto_actions.set_enabled", {"slotIndex": slot, "enabled": desired["enabled"]})
    for extra in remaining:
        if extra["enabled"]:
            connection.request("auto_actions.set_enabled", {"slotIndex": extra["slotIndex"], "enabled": False})
    if setup["active"]:
        connection.request("auto_actions.set_active", {"active": True})


def candidate(profiles, amount):
    eligible = [(threshold(p["minimum"]), name) for name, p in profiles.items()
                if p["minimum"] is not None and threshold(p["minimum"]) <= amount]
    return max(eligible)[1] if eligible else None


class SetupSwitcher:
    def __init__(self, db_path):
        self.db_path = db_path
        self.next_check = 0.0
        self.worker = None
        self.error = ""

    def step(self, db, live, enabled, snap):
        now = time.monotonic()
        if not (live and snap.get("market_ready")) or now < self.next_check:
            return
        if self.worker is not None and self.worker.is_alive():
            return
        self.next_check = now + CHECK_SECONDS
        if not config(db)["profiles"]:
            return
        self.worker = threading.Thread(target=self._run, args=(snap, enabled), daemon=True, name="automation-setups")
        self.worker.start()

    def _run(self, snap, enabled):
        db = Storage(self.db_path)
        try:
            self._evaluate(db, snap, enabled)
            self.error = ""
        except game_bridge.BridgeError as exc:
            self.error = str(exc)
            log.debug("Automation setup: %s", exc)
        except Exception:
            self.error = "Could not apply automation setup"
            log.exception("Automation setup failed")
        finally:
            db.close()

    def _evaluate(self, db, snap, enabled=True):
        cfg = config(db)
        profiles = cfg["profiles"]
        manual = load(db, MANUAL, {})
        state = load(db, STATE, {})
        ipo = snap.get("ipo_count")
        before = state.get("ipo")
        reset = ipo is not None and before is not None and ipo > before
        amount = snap.get(cfg["metric"])
        match = candidate(profiles, amount) if amount is not None else None
        previous = state.get("candidate")
        target = None
        if manual.get("id") and manual["id"] != state.get("manual"):
            target = manual["name"]
        elif enabled and cfg["enabled"] and (reset or not state.get("automatic") or match != previous):
            active = profiles.get(state.get("active"), {})
            floor = active.get("minimum")
            if reset or cfg["switch_back"] or floor is None or (match and threshold(profiles[match]["minimum"]) >= threshold(floor)):
                target = match
        if target in profiles:
            profile = profiles[target]
            if profile["bot"] is not None:
                preset = bot.BotSettings.from_dict(profile["bot"])
                if preset != bot.load_settings(db):
                    bot.save_settings(db, preset)
            if profile["game"] is not None:
                connection = client()
                try:
                    apply_actions(connection, profile["game"])
                finally:
                    connection.close()
            state["active"] = target
        state.update(candidate=match, automatic=enabled and cfg["enabled"], manual=manual.get("id"))
        if ipo is not None and (before is None or ipo >= before):
            state["ipo"] = ipo
        if state != load(db, STATE, {}):
            save(db, STATE, state)


def save_profile(db, name, minimum, capture_bot, game):
    name = name.strip()
    if not name or len(name) > 80:
        raise ValueError("Enter a setup name of 1–80 characters")
    cfg = config(db)
    numeric = threshold(minimum) if minimum else None
    if numeric is not None and any(n != name and p["minimum"] is not None and threshold(p["minimum"]) == numeric
                                   for n, p in cfg["profiles"].items()):
        raise ValueError("Another setup already uses that threshold")
    old = cfg["profiles"].get(name, {})
    preset = asdict(bot.load_settings(db)) if capture_bot else old.get("bot")
    actions = game if game is not None else old.get("game")
    if preset is None and actions is None:
        raise ValueError("Capture bot settings or in-game Auto Actions")
    cfg["profiles"][name] = {"minimum": minimum or None, "bot": preset, "game": actions}
    save(db, CONFIG, cfg)
