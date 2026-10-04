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

# GitHub repository used for the update check.
GITHUB_REPO = "DvTJ/ScreenStocksTradingUI"

# Prices and snapshots older than this are thinned out to one row per bucket at start-up.
RETENTION_DAYS = 7
COMPACT_BUCKET_MS = 10_000
