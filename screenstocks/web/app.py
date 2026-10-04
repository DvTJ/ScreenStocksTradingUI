"""Starts the web UI window."""

import logging
from pathlib import Path

import webview

from .. import __version__
from ..automation import AutomationEngine
from ..collector import Collector
from ..i18n import t
from ..settings import resource_path
from .bridge import Bridge

log = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"


def static_dir() -> Path:
    # inside a PyInstaller build the files live next to the bundled modules
    bundled = resource_path("screenstocks/web/static")
    return bundled if bundled.is_dir() else STATIC


def run(collector: Collector, engine: AutomationEngine, db_path: Path, export_dir: Path,
        debug: bool = False) -> None:
    bridge = Bridge(collector, engine, db_path, export_dir)
    window = webview.create_window(
        f"{t('app.title')}  v{__version__}", str(static_dir() / "index.html"), js_api=bridge,
        width=1500, height=930, min_size=(1100, 700), background_color="#0f1012", text_select=False)
    bridge._attach(window)
    window.events.closed += bridge._shutdown
    icon = resource_path("assets/icon.ico")
    webview.start(debug=debug, icon=str(icon) if icon.exists() else None)
    bridge._shutdown()
