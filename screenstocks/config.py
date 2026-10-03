import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

DEFAULT_EXPORT_DIR = (
    Path(os.environ.get("USERPROFILE", str(Path.home())))
    / "AppData" / "LocalLow" / "Conradical Games" / "Screen Stocks" / "mods" / "export"
)

MARKET_FILE = "market.json"
HISTORY_FILE = "history.json"

# How often the collector checks the export files for changes (seconds).
POLL_INTERVAL_S = 0.25
# How often the GUI refreshes (milliseconds).
GUI_REFRESH_MS = 1000
# Data older than this is treated as "not live" (milliseconds).
STALE_AFTER_MS = 5000
