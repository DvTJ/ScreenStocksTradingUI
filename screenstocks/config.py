import os
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

# The game's Unity persistentDataPath below one of game_data_roots().
GAME_DIR = Path("Conradical Games") / "Screen Stocks"
STEAM_APP_IDS = ("4356780", "5124200")   # full game, demo


def steam_libraries() -> list:
    """Linux Steam library folders: native, Flatpak and Snap roots plus libraryfolders.vdf entries."""
    home = Path.home()
    roots = [home / ".steam" / "steam", home / ".local" / "share" / "Steam",
             home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
             home / "snap" / "steam" / "common" / ".local" / "share" / "Steam"]
    libs = list(roots)
    for root in roots:
        try:
            text = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        libs += [Path(p) for p in re.findall(r'"path"\s+"([^"]+)"', text)]
    unique, seen = [], set()
    for lib in libs:
        try:
            key = lib.resolve()   # ~/.steam/steam usually links to ~/.local/share/Steam
        except (OSError, RuntimeError, ValueError):
            continue
        if key not in seen:
            seen.add(key)
            unique.append(lib)
    return unique


def game_data_roots() -> list:
    """Folders that may hold GAME_DIR on this OS, most likely first."""
    home = Path.home()
    if sys.platform == "win32":
        return [Path(os.environ.get("USERPROFILE", str(home))) / "AppData" / "LocalLow"]
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support"]
    # No native Linux build: the Windows build runs under Steam Proton.
    proton = Path("pfx") / "drive_c" / "users" / "steamuser" / "AppData" / "LocalLow"
    libs = steam_libraries()
    return ([lib / "steamapps" / "compatdata" / app / proton for app in STEAM_APP_IDS for lib in libs]
            + [Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "unity3d"])


def default_export_dir() -> Path:
    """Export folder in the first root that holds the game, else in the most likely root."""
    roots = game_data_roots()
    root = next((r for r in roots if (r / GAME_DIR).is_dir()), roots[0])
    return root / GAME_DIR / "mods" / "export"


DEFAULT_EXPORT_DIR = default_export_dir()

MARKET_FILE = "market.json"
HISTORY_FILE = "history.json"

# How often the collector checks the export files for changes (seconds).
POLL_INTERVAL_S = 0.1
# How often the GUI refreshes (milliseconds).
GUI_REFRESH_MS = 1000
# Data older than this is treated as "not live" (milliseconds).
STALE_AFTER_MS = 5000

# GitHub repository used for the update check.
GITHUB_REPO = "DvTJ/ScreenStocksTradingUI"

# Prices and snapshots older than this are thinned out to one row per bucket at start-up.
RETENTION_DAYS = 7
COMPACT_BUCKET_MS = 10_000
