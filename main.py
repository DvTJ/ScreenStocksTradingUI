"""ScreenStocks Trading Bot.

    python main.py              # dashboard + recording (setup wizard on first start)
    python main.py --setup      # run the setup wizard again
    python main.py --headless   # record + automation only, no window
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from screenstocks import __version__, settings as settings_mod
from screenstocks.automation import AutomationEngine
from screenstocks.collector import Collector
from screenstocks.commands import CommandWriter
from screenstocks.i18n import set_language, system_language


def setup_logging(verbose: bool) -> None:
    handlers: list[logging.Handler] = []
    log_dir = settings_mod.user_data_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "app.log", encoding="utf-8"))
    except OSError:
        pass
    if sys.stderr is not None:  # a windowed (PyInstaller) build has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> int:
    ap = argparse.ArgumentParser(description="Reads the Screen Stocks mod export, records a history and trades.")
    ap.add_argument("--export-dir", type=Path, help="folder containing market.json / history.json")
    ap.add_argument("--db", type=Path, help="SQLite file for the history")
    ap.add_argument("--headless", action="store_true", help="record without a window")
    ap.add_argument("--setup", action="store_true", help="run the setup wizard")
    ap.add_argument("--lang", choices=["de", "en"], help="UI language for this run")
    ap.add_argument("--ui", choices=["web", "classic"], help="user interface for this run (default: settings)")
    ap.add_argument("--debug-ui", action="store_true", help="web UI with developer tools")
    ap.add_argument("--version", action="version", version=f"ScreenStocks Trading Bot {__version__}")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger("main")
    settings = settings_mod.load()
    set_language(args.lang or settings.language or system_language())

    if not args.headless and (args.setup or not settings.setup_done):
        from screenstocks.gui.setup import run_setup
        result = run_setup(settings)
        if result is None:
            if not settings.setup_done:
                return 0  # wizard cancelled on first start
        else:
            settings = result
        set_language(args.lang or settings.language or system_language())

    export_dir = args.export_dir or settings.export_path
    db_path = args.db or settings.db_file
    log.info("ScreenStocks Trading Bot %s – export: %s, db: %s", __version__, export_dir, db_path)
    if not export_dir.is_dir():
        log.warning("export folder does not exist (yet): %s – waiting for it", export_dir)

    collector = Collector(export_dir, db_path)
    collector.start()
    # Stop-loss / take-profit / ... rules run in the background, also in headless mode.
    engine = AutomationEngine(collector, db_path, CommandWriter(export_dir.parent))
    engine.start()

    if args.headless:
        log.info("recording %s -> %s (Ctrl+C to stop)", export_dir, db_path)
        try:
            while True:
                time.sleep(10)
                st = collector.status.copy()
                log.info("snapshots %s  prices %s  errors %s  market.json %s  automation %s",
                         st.snapshots_stored, st.samples_stored, st.read_errors,
                         "yes" if st.market_found else "no", engine.state)
        except KeyboardInterrupt:
            pass
        engine.stop()
        collector.stop()
        collector.join(timeout=2)
        return 0

    ui = args.ui or settings.ui
    if ui == "web":
        from screenstocks.web import webview_available
        ok, reason = webview_available()
        if ok:
            try:
                from screenstocks.web.app import run as run_web
                run_web(collector, engine, db_path, export_dir, debug=args.debug_ui)
                collector.join(timeout=2)
                return 0
            except Exception as exc:  # e.g. WebView2 failed to start
                reason = f"{type(exc).__name__}: {exc}"
                log.exception("web UI failed, falling back to the classic interface")
        log.warning("web UI not available (%s) - starting the classic interface", reason)
        _show_web_fallback(reason)

    from screenstocks.gui.app import run
    run(collector, engine, db_path, export_dir)
    collector.join(timeout=2)
    return 0


def _show_web_fallback(reason: str) -> None:
    """Explain once why the classic interface starts instead of the web UI."""
    import tkinter as tk
    from tkinter import messagebox
    from screenstocks.i18n import t
    from screenstocks.web import WEBVIEW2_DOWNLOAD
    root = tk.Tk()
    root.withdraw()
    if messagebox.askyesno(t("web.fallback_title"), t("web.fallback_text", reason=reason), parent=root):
        import webbrowser
        webbrowser.open(WEBVIEW2_DOWNLOAD)
    root.destroy()


if __name__ == "__main__":
    sys.exit(main())
