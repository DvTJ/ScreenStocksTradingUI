"""Starts the web UI window."""

import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import webview

from .. import __version__
from ..automation import AutomationEngine
from ..collector import Collector
from ..i18n import t
from ..settings import resource_path
from . import qt_sandbox_fix
from .bridge import Bridge

log = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"


def static_dir() -> Path:
    # inside a PyInstaller build the files live next to the bundled modules
    bundled = resource_path("screenstocks/web/static")
    return bundled if bundled.is_dir() else STATIC


SMOKE_TIMEOUT_S = 90


def _smoke_test(window, result: dict) -> None:
    """--smoke-test (CI): wait until the page shows its tabs - the page, its scripts and the Python bridge (init)
    work - then close the window. A page that never loads ends the process with exit code 2."""
    watchdog = threading.Timer(SMOKE_TIMEOUT_S + 30, lambda: os._exit(2))
    watchdog.daemon = True
    watchdog.start()
    deadline = time.monotonic() + SMOKE_TIMEOUT_S
    while time.monotonic() < deadline and not result.get("tabs"):
        try:
            result["tabs"] = int(window.evaluate_js("document.querySelectorAll('#tabs button').length") or 0)
        except Exception as exc:  # page not ready yet
            log.debug("smoke test: %s", exc)
        if not result.get("tabs"):
            time.sleep(0.5)
    log.info("smoke test: %s tabs, renderer %s", result.get("tabs", 0), getattr(webview, "renderer", None))
    window.destroy()


def run(start_backend: Callable[[], tuple[Collector, AutomationEngine, Path, Path]], setup: bool = False,
        debug: bool = False, smoke: bool = False) -> bool:
    """start_backend starts recording + automation and returns (collector, engine, db_path, export_dir).
    With setup=True the window first shows the setup wizard and starts the backend when it is finished.
    smoke=True closes the window again once the page works; the result says whether it did."""
    bridge = Bridge()
    bridge._backend_factory = start_backend
    if not setup:
        bridge._start(*start_backend())
    page = static_dir() / ("setup.html" if setup else "index.html")
    window = webview.create_window(
        f"{t('app.title')}  v{__version__}", str(page), js_api=bridge,
        width=1500, height=930, min_size=(900, 600), background_color="#0f1012", text_select=False)
    bridge._attach(window)
    window.events.closed += bridge._shutdown
    if sys.platform.startswith("linux"):
        qt_sandbox_fix()
    icon = resource_path("assets/icon.ico" if sys.platform == "win32" else "assets/icon.png")  # GTK / Qt want a png
    result: dict = {}
    webview.start(_smoke_test if smoke else None, (window, result) if smoke else None,
                  debug=debug, icon=str(icon) if icon.exists() else None)
    bridge._shutdown()
    return bool(result.get("tabs")) if smoke else True
