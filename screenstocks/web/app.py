"""Starts the web UI window."""

import logging
from pathlib import Path
from typing import Callable

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


def run(start_backend: Callable[[], tuple[Collector, AutomationEngine, Path, Path]], setup: bool = False,
        debug: bool = False) -> None:
    """start_backend starts recording + automation and returns (collector, engine, db_path, export_dir).
    With setup=True the window first shows the setup wizard and starts the backend when it is finished."""
    bridge = Bridge()
    bridge._backend_factory = start_backend
    if not setup:
        bridge._start(*start_backend())
    page = static_dir() / ("setup.html" if setup else "index.html")
    window = webview.create_window(
        f"{t('app.title')}  v{__version__}", str(page), js_api=bridge,
        width=1500, height=930, min_size=(1100, 700), background_color="#0f1012", text_select=False)
    bridge._attach(window)
    window.events.closed += bridge._shutdown
    icon = resource_path("assets/icon.ico")
    webview.start(debug=debug, icon=str(icon) if icon.exists() else None)
    bridge._shutdown()
