"""Sending trade commands to the game through the mod's command files.

The mod watches mods/commands/<stockId>/<action>.json. Writing
{"execute": true, "percent": N} triggers the trade; the outcome shows up in
market.json -> commandResults. The game rounds the percentage to a whole
number and clamps it to 1..100.
"""

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .i18n import t

# action key -> command file prefix (<prefix>percent.json / <prefix>max.json)
ACTIONS = {"buy": "buy", "sell": "sell", "short": "short", "cover": "cover", "close": "close"}


def action_name(action: str) -> str:
    return t(f"action.{action}")


def reason_text(code: Optional[str]) -> str:
    """Translate a reason code written by the game into commandResults."""
    return t(f"reason.{code}", default=code) if code else ""


def status_text(code: Optional[str]) -> str:
    return t(f"cmdstatus.{code}", default=code or "")


def action_label(game_action: str) -> str:
    """'buypercent' -> 'Buy', 'sellmax' -> 'Sell (max)'."""
    for key, prefix in ACTIONS.items():
        if game_action == f"{prefix}percent":
            return action_name(key)
        if game_action == f"{prefix}max":
            return action_name(key) + t("action.max_suffix")
    return game_action


def _replace(src: Path, dst: Path, attempts: int = 40, delay_s: float = 0.025) -> None:
    """Atomic replace that tolerates the game holding the file open for a moment.

    The mod reads every command file about every 50 ms; on Windows replacing a file
    that is open in another process fails with "access denied", so retry briefly.
    """
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_s)


def normalize_percent(value: float) -> int:
    """Same rounding the game applies (Mathf.RoundToInt + Clamp 1..100)."""
    return max(1, min(100, int(round(float(value)))))


@dataclass
class SentCommand:
    stock_id: str
    action: str
    percent: int
    path: Path


class CommandWriter:
    # The game allows ~1 command per second (burst 10); stay safely below.
    MIN_SPACING_S = 1.1

    def __init__(self, mods_dir: Path):
        self.mods_dir = Path(mods_dir)
        self.commands_dir = self.mods_dir / "commands"
        self._lock = threading.Lock()  # shared by the trade panel and the automation thread
        self._last_send = 0.0

    def commands_enabled(self) -> Optional[bool]:
        """Value of "commands" in mod-settings.json (None if unreadable)."""
        try:
            with open(self.mods_dir / "mod-settings.json", encoding="utf-8-sig") as fh:
                return bool(json.load(fh).get("commands", False))
        except (OSError, ValueError):
            return None

    def send(self, stock_id: str, action: str, percent: float) -> SentCommand:
        if action not in ACTIONS:
            raise ValueError(t("cmd.unknown_action", action=action))
        stock_dir = self.commands_dir / stock_id
        if not stock_dir.is_dir():
            raise FileNotFoundError(t("cmd.folder_missing", path=stock_dir))
        pct = normalize_percent(percent)
        path = stock_dir / f"{ACTIONS[action]}percent.json"
        tmp = path.with_suffix(".json.tmp")
        with self._lock:
            wait = self._last_send + self.MIN_SPACING_S - time.time()
            if wait > 0:
                time.sleep(wait)
            tmp.write_text(json.dumps({"execute": True, "percent": pct}, indent=2), encoding="utf-8")
            # Atomic replace so the game never sees a half-written file.
            _replace(tmp, path)
            self._last_send = time.time()
        return SentCommand(stock_id, action, pct, path)

    def cancel(self, sent: SentCommand) -> bool:
        """Disarm a command the game has not picked up yet, so it cannot fire later
        (e.g. on the next game start). Returns True if it was still pending."""
        with self._lock:
            if not self.is_pending(sent):
                return False
            tmp = sent.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"execute": False, "percent": sent.percent}, indent=2), encoding="utf-8")
            _replace(tmp, sent.path)
            return True

    def is_pending(self, sent: SentCommand) -> bool:
        """True while the game has not yet consumed the file (execute still true)."""
        try:
            with open(sent.path, encoding="utf-8-sig") as fh:
                return bool(json.load(fh).get("execute"))
        except (OSError, ValueError):
            return False
