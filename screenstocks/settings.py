"""Persistent user settings and per-user paths.

settings.json lives in %APPDATA%\\ScreenStocksTradingBot, the database and log
in %LOCALAPPDATA%\\ScreenStocksTradingBot - the install folder may be read-only.
"""

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from . import config

APP_NAME = "ScreenStocksTradingBot"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_path(relative: str) -> Path:
    """Path to a bundled file (works from source and inside a PyInstaller build)."""
    base = Path(getattr(sys, "_MEIPASS", config.PROJECT_DIR))
    return base / relative


def user_config_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / APP_NAME


def user_data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME


SETTINGS_FILE = user_config_dir() / "settings.json"


def default_db_path() -> Path:
    # Keep using the database of a source checkout that already recorded history.
    legacy = config.PROJECT_DIR / "data" / "screenstocks.db"
    if not is_frozen() and legacy.exists():
        return legacy
    return user_data_dir() / "screenstocks.db"


def normalize_export_dir(path: Path) -> Path:
    """Accept the export folder itself, the mods folder or the game's LocalLow folder."""
    path = Path(path)
    for candidate in (path, path / "export", path / "mods" / "export"):
        if (candidate / config.MARKET_FILE).exists() or (candidate / config.HISTORY_FILE).exists():
            return candidate
    if path.name.lower() == "mods" and (path / "export").is_dir():
        return path / "export"
    if (path / "mods" / "export").is_dir():
        return path / "mods" / "export"
    return path


def detect_export_dir() -> Optional[Path]:
    candidates = [config.DEFAULT_EXPORT_DIR]
    locallow = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "AppData" / "LocalLow"
    if locallow.is_dir():
        # also catch renamed studio/game folders, e.g. a demo build
        candidates += sorted(locallow.glob("*/Screen Stocks*/mods/export"))
    for c in candidates:
        if c.is_dir():
            return c
    return None


@dataclass
class Settings:
    language: str = ""
    export_dir: str = ""
    db_path: str = ""
    setup_done: bool = False
    check_updates: bool = True
    stock_colors: dict = field(default_factory=dict)   # stock id -> "#rrggbb"

    @property
    def export_path(self) -> Path:
        return Path(self.export_dir) if self.export_dir else (detect_export_dir() or config.DEFAULT_EXPORT_DIR)

    @property
    def db_file(self) -> Path:
        return Path(self.db_path) if self.db_path else default_db_path()


# Colours handed out to stocks in order of first appearance; a stock keeps its colour.
PALETTE = ["#58a6ff", "#3fb950", "#f0883e", "#d2a8ff", "#ff7b72",
           "#56d4dd", "#e3b341", "#a5d6ff", "#7ee787", "#ffa198"]


def default_colors(stock_ids) -> dict:
    return {sid: PALETTE[i % len(PALETTE)] for i, sid in enumerate(sorted(stock_ids))}


def assign_colors(settings: "Settings", stock_ids) -> bool:
    """Give new stocks a colour that is not taken yet. Returns True if settings changed."""
    colors = settings.stock_colors
    changed = False
    for sid in sorted(stock_ids):
        if sid not in colors:
            used = set(colors.values())
            colors[sid] = next((c for c in PALETTE if c not in used), PALETTE[len(colors) % len(PALETTE)])
            changed = True
    return changed


def load() -> Settings:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in Settings.__dataclass_fields__}
        return Settings(**known)
    except (OSError, ValueError, TypeError):
        return Settings()


def save(settings: Settings) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


def read_mod_settings(export_dir: Path) -> Optional[dict]:
    try:
        return json.loads((Path(export_dir).parent / "mod-settings.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def enable_mod_features(export_dir: Path) -> None:
    """Set export and commands to true in the game's mod-settings.json (other keys untouched)."""
    path = Path(export_dir).parent / "mod-settings.json"
    data = read_mod_settings(export_dir) or {}
    data["export"] = True
    data["commands"] = True
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=4), encoding="utf-8")
    os.replace(tmp, path)


def restart_app() -> None:
    """Start a fresh instance of the app (the caller closes the current one)."""
    args = [a for a in sys.argv[1:] if a != "--setup"]
    cmd = [sys.executable, *args] if is_frozen() else [sys.executable, sys.argv[0], *args]
    subprocess.Popen(cmd, close_fds=True)
