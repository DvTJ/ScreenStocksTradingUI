"""Export / import of the automation configuration as a JSON file.

Covers the rules, the pump/crash event settings and the bot settings - each part
is optional. Importing adds the rules (identical ones are skipped) and replaces
only the settings blocks present in the file.
"""

import json
import time
from dataclasses import asdict

from . import bot, events
from .automation import KIND_KEYS, MODE_KEYS, SIDE_KEYS
from .storage import Storage

FORMAT = "screenstocks-automation"
RULE_FIELDS = ("stock_id", "kind", "side", "mode", "value", "percent", "confirm_s", "repeat")


def export_config(db: Storage, rule_ids=None, with_events: bool = True, with_bot: bool = False) -> dict:
    """rule_ids: rules to include (None = all). Unchosen parts are left out of the file."""
    data = {"format": FORMAT, "version": 1}
    rules = [r for r in db.rules() if rule_ids is None or r["id"] in rule_ids]
    if rules:
        data["rules"] = [{**{k: r[k] for k in RULE_FIELDS}, "repeat": bool(r["repeat"]), "enabled": bool(r["enabled"])}
                         for r in rules]
    if with_events:
        data["events"] = asdict(events.load_settings(db))
    if with_bot:
        data["bot"] = asdict(bot.load_settings(db))
    return data


def import_config(db: Storage, data: dict) -> int:
    """Apply a config produced by export_config. Returns the number of rules added.
    Raises ValueError for a file that is not an automation config."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a ScreenStocks automation config")
    known = {(r["stock_id"], r["kind"], r["side"], r["mode"], r["value"], r["percent"]) for r in db.rules()}
    added = 0
    for r in data.get("rules", []):
        if r.get("kind") not in KIND_KEYS or r.get("side") not in SIDE_KEYS or r.get("mode") not in MODE_KEYS:
            raise ValueError(f"invalid rule: {r}")
        key = (r["stock_id"], r["kind"], r["side"], r["mode"], float(r["value"]), int(r["percent"]))
        if key in known:
            continue
        rid = db.add_rule(r["stock_id"], r["kind"], r["side"], r["mode"], float(r["value"]), int(r["percent"]),
                          float(r.get("confirm_s", 0)), int(time.time() * 1000), bool(r.get("repeat")))
        if not r.get("enabled", True):
            db.update_rule(rid, enabled=0)
        known.add(key)
        added += 1
    if "events" in data:
        ev = {k: v for k, v in data["events"].items() if k in events.EventSettings.__dataclass_fields__}
        events.save_settings(db, events.EventSettings(**ev))
    if "bot" in data:
        bt = {k: v for k, v in data["bot"].items() if k in bot.BotSettings.__dataclass_fields__}
        now = bot.load_settings(db)
        bt["enabled"], bt["paper"] = now.enabled, now.paper      # a shared file never switches the bot on or off
        bot.save_settings(db, bot.BotSettings(**bt))
    return added


def save_file(db: Storage, path, **choice) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(export_config(db, **choice), fh, indent=2, ensure_ascii=False)


def load_file(db: Storage, path) -> int:
    with open(path, encoding="utf-8-sig") as fh:
        return import_config(db, json.load(fh))
