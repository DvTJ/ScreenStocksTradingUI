"""Bridge between Python and the web UI (exposed to JavaScript as window.pywebview.api).

pywebview calls these methods on worker threads, so all database access goes
through one shared connection guarded by a lock. Only public methods are visible
to JavaScript; internal state lives in underscore attributes.
"""

import logging
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from .. import __version__, config, settings as settings_mod, updater
from ..automation import AutomationEngine
from ..collector import Collector
from ..i18n import get_language, texts
from ..storage import Storage
from .automation_api import AutomationApi
from .market import MarketApi
from .analysis_api import AnalysisApi
from .portfolio_api import PortfolioApi
from .settings_api import SettingsApi

log = logging.getLogger(__name__)

ALLOWED_LINKS = ("https://www.tradingview.com/", "https://github.com/", "https://developer.microsoft.com/",
                 "https://www.apache.org/", "https://www.python.org/")


class Bridge(MarketApi, AutomationApi, PortfolioApi, AnalysisApi, SettingsApi):
    def __init__(self, collector: Optional[Collector] = None, engine: Optional[AutomationEngine] = None,
                 db_path: Optional[Path] = None, export_dir: Optional[Path] = None):
        self._collector = self._engine = self._db = self._slow_db = self._export_dir = None
        self._lock = threading.Lock()
        self._slow_lock = threading.Lock()
        self._settings = settings_mod.load()
        self._window = None
        self._update: dict = {}            # latest release info + download progress for the UI
        self._update_checked = False
        self._closing = False
        self._backend_factory = None       # set by app.run when the setup wizard runs first
        if collector is not None:
            self._start(collector, engine, db_path, export_dir)

    def _start(self, collector: Collector, engine: AutomationEngine, db_path: Path, export_dir: Path) -> None:
        self._collector = collector
        self._engine = engine
        self._export_dir = export_dir
        self._db = Storage(db_path, shared=True)
        # second connection for slow read-only calculations (statistics), so they never block the 1 s tick
        self._slow_db = Storage(db_path, shared=True)

    # ---------------------------------------------------------------- lifecycle

    def _attach(self, window) -> None:
        self._window = window

    def _shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True        # page calls arriving from now on get empty answers
        if self._collector is None:  # window closed during the setup wizard
            return
        self._engine.stop()
        self._collector.stop()
        with self._lock:
            self._db.close()
        with self._slow_lock:
            self._slow_db.close()

    def _open_app(self) -> None:
        """After the setup wizard: start the backend and load the app page into the same window."""
        from .app import static_dir
        if self._collector is None:
            self._start(*self._backend_factory())
        self._settings = settings_mod.load()
        url = (static_dir() / "index.html").as_uri()
        # navigate only after this call has returned its result to the wizard page
        threading.Timer(0.2, lambda: self._window.load_url(url)).start()

    def _close_window(self) -> None:
        if self._window is not None:
            self._window.destroy()

    # ------------------------------------------------------------------ startup

    def init(self) -> dict:
        """Everything the page needs once: language, texts, version, colours, settings."""
        lang = get_language()
        if self._settings.check_updates and not self._update_checked:   # init runs again after a reload
            self._update_checked = True
            threading.Thread(target=self._check_updates, daemon=True).start()
        return {"lang": lang, "texts": texts(lang), "version": __version__, "colors": self._settings.stock_colors,
                "frozen": settings_mod.is_frozen(), "ui": self._settings.ui,
                "github": f"https://github.com/{config.GITHUB_REPO}"}

    # --------------------------------------------------------------------- tick

    def tick(self) -> dict:
        """Called by the page every second: header values, status bar and update state."""
        if self._closing:
            return {}
        with self._lock:
            db = self._db
            st = self._collector.status.copy()
            snap = db.latest_snapshot() or {}
            live = bool(st.last_market_read) and time.time() - st.last_market_read < config.STALE_AFTER_MS / 1000
            server_now = snap.get("server_ms")
            if server_now and st.last_market_read:
                server_now += int((time.time() - st.last_market_read) * 1000)
            counts = db.counts()
        cd = lambda col: ((snap.get(col) or 0) - server_now) / 1000 if server_now and snap.get(col) else None  # noqa: E731
        return {
            "live": live, "market_found": st.market_found, "server_now": server_now,
            "net": snap.get("net_worth"), "cash": snap.get("cash"), "level": snap.get("level"),
            "sequence": snap.get("sequence"), "buy_cd": cd("next_buy_ms"), "short_cd": cd("next_short_ms"),
            "engine": self._engine.state, "game_version": st.game_version,
            "read_errors": st.read_errors, "last_error": st.last_error,
            "source": str(self._export_dir), "db": Path(db.path).name, "counts": counts,
            "update": dict(self._update),
        }

    # ------------------------------------------------------------------ updates

    def _check_updates(self) -> None:
        try:
            release = updater.fetch_latest()
        except Exception as exc:
            log.info("update check failed: %s", exc)
            return
        if updater.is_newer(release.version):
            self._update = {"version": release.version, "page": release.page_url,
                            "installer": bool(release.installer_url) and settings_mod.is_frozen(),
                            "state": "available"}
            self._release = release

    def check_updates_now(self) -> dict:
        """Manual check from the settings; returns {"state": ..., "version": ...}."""
        try:
            release = updater.fetch_latest()
        except Exception as exc:
            return {"state": "failed", "error": str(exc)}
        if updater.is_newer(release.version):
            self._release = release
            self._update = {"version": release.version, "page": release.page_url,
                            "installer": bool(release.installer_url) and settings_mod.is_frozen(),
                            "state": "available"}
            return {"state": "available", "version": release.version}
        return {"state": "current", "version": __version__}

    def install_update(self) -> None:
        """Download the installer in the background, start it and close the app."""
        release = getattr(self, "_release", None)
        if not release or not release.installer_url or self._update.get("state") == "downloading":
            return
        self._update.update(state="downloading", progress=0)

        def progress(done: int, total: int) -> None:
            self._update["progress"] = int(done * 100 / total) if total else 0

        def work() -> None:
            try:
                path = updater.download_installer(release, progress)
                updater.launch_installer(path)
                self._update["state"] = "installing"
                time.sleep(0.5)
                self._shutdown()
                self._close_window()
            except Exception as exc:
                self._update.update(state="failed", error=str(exc))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ settings

    def restart(self) -> None:
        self._shutdown()
        settings_mod.restart_app()
        self._close_window()

    # -------------------------------------------------------------------- misc

    def open_url(self, url: str) -> None:
        if isinstance(url, str) and url.startswith(ALLOWED_LINKS):
            webbrowser.open(url)

    def log_client_error(self, message: str) -> None:
        """JavaScript errors end up in app.log, too."""
        log.warning("web ui: %s", str(message)[:2000])
