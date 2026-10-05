"""Settings dialog and setup wizard of the web UI.

Mixed into Bridge (bridge.py). Same rules as the classic SettingsDialog and
SetupWizard: colours and the update switch apply immediately, the language is
switched live (the page reloads), interface, folders and database need a restart.
"""

import importlib.metadata
import logging
import platform
import sqlite3
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

import webview

from .. import __version__, config, settings as settings_mod
from ..i18n import LANGUAGES, get_language, set_language, t, texts
from ..storage import Storage

log = logging.getLogger(__name__)

# shown under Settings -> About (name, distribution for the version, licence, link)
LIBRARIES = [
    ("pywebview", "pywebview", "BSD-3-Clause", "https://github.com/r0x0r/pywebview"),
    ("pythonnet", "pythonnet", "MIT", "https://github.com/pythonnet/pythonnet"),
    ("TradingView Lightweight Charts™", None, "Apache-2.0", "https://github.com/tradingview/lightweight-charts"),
]
CHARTS_VERSION = "5.2.1"     # vendored file in static/vendor


def _dist_version(name: Optional[str]) -> Optional[str]:
    if not name:
        return CHARTS_VERSION
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:       # frozen build without metadata
        return None


class SettingsApi:
    # ---------------------------------------------------------------- helpers

    def _save_dialog(self, directory: str, filename: str) -> Optional[str]:
        """Save dialog without the "replace existing file?" question: an existing database is
        opened, not overwritten (same as the classic dialog with confirmoverwrite=False)."""
        try:
            from webview.platforms.winforms import BrowserView, WinForms
            owner = BrowserView.instances.get(self._window.uid)
            dialog = WinForms.SaveFileDialog()
            dialog.Filter = "SQLite (*.db)|*.db|* (*.*)|*.*"
            dialog.InitialDirectory = directory
            dialog.FileName = filename
            dialog.OverwritePrompt = False
            dialog.DefaultExt = "db"
            if dialog.ShowDialog(owner) == WinForms.DialogResult.OK:
                return str(dialog.FileName)
            return None
        except Exception:
            log.exception("own save dialog failed - using the pywebview dialog")
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=directory, save_filename=filename,
                                                 file_types=("SQLite (*.db)", "All files (*.*)"))
        return str(result[0] if isinstance(result, (tuple, list)) else result) if result else None

    def check_export(self, path: str) -> dict:
        """Checks of the export folder (same lines as the classic wizard)."""
        p = Path(path or "")
        ok = bool(path) and p.is_dir()
        mods = settings_mod.read_mod_settings(p) if path else None
        return {"dir_ok": ok, "market_ok": ok and (p / config.MARKET_FILE).exists(),
                "mods": None if mods is None else {"export": bool(mods.get("export")),
                                                   "commands": bool(mods.get("commands"))}}

    def browse_export(self, start: str) -> Optional[str]:
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start if Path(start or "").is_dir() else "")
        if not result:
            return None
        chosen = result[0] if isinstance(result, (tuple, list)) else result
        return str(settings_mod.normalize_export_dir(Path(chosen)))

    def detect_export(self) -> Optional[str]:
        found = settings_mod.detect_export_dir()
        return str(found) if found else None

    def browse_db(self, current: str) -> Optional[str]:
        cur = Path(current or settings_mod.default_db_path())
        return self._save_dialog(str(cur.parent) if cur.parent.is_dir() else "", cur.name)

    def db_exists(self, path: str) -> bool:
        return bool(path) and Path(path).is_file()

    def _enable_mods(self, export_dir: Path, wanted: bool) -> Optional[str]:
        """Switch on export + commands in mod-settings.json if asked; returns an error text."""
        mods = settings_mod.read_mod_settings(export_dir)
        if mods is None or not wanted or (mods.get("export") and mods.get("commands")):
            return None
        try:
            settings_mod.enable_mod_features(export_dir)
        except OSError as exc:
            return str(exc)
        return None

    # --------------------------------------------------------------- settings

    def settings_get(self) -> dict:
        """Everything the settings dialog shows."""
        s = settings_mod.load()
        ids = set(s.stock_colors)
        if self._db is not None and not self._closing:
            with self._lock:
                ids |= set(self._db.stock_ids())
        return {"language": s.language or get_language(), "languages": LANGUAGES, "ui": s.ui or "web",
                "export_dir": str(s.export_path), "db_path": str(s.db_file), "check_updates": s.check_updates,
                "colors": s.stock_colors, "stocks": sorted(ids), "palette": settings_mod.PALETTE,
                "defaults": settings_mod.default_colors(sorted(ids)),
                "retention_days": config.RETENTION_DAYS, "bucket_s": config.COMPACT_BUCKET_MS // 1000}

    def save_settings(self, values: dict) -> dict:
        """Saves the dialog. Returns {reload, restart, warning}."""
        current = settings_mod.load()
        export_dir = Path(values.get("export_dir") or current.export_path)
        warning = self._enable_mods(export_dir, bool(values.get("enable_mods")))
        colors = {str(k): str(v) for k, v in (values.get("colors") or {}).items()}
        new = replace(current, language=values.get("language") or current.language,
                      ui=values.get("ui") if values.get("ui") in ("web", "classic") else current.ui,
                      export_dir=str(export_dir), db_path=str(values.get("db_path") or current.db_file),
                      check_updates=bool(values.get("check_updates")), stock_colors=colors or current.stock_colors)
        settings_mod.save(new)
        self._settings = new
        reload = new.language != get_language()
        if reload:
            set_language(new.language)
        # the running backend uses these paths; compare with what was actually started
        restart = (new.ui != (current.ui or "web") or Path(new.export_dir) != Path(self._export_dir or "")
                   or Path(new.db_path) != Path(self._db.path if self._db is not None else ""))
        return {"reload": reload, "restart": restart, "warning": warning}

    def db_info(self) -> dict:
        with self._lock:
            info = self._db.db_info()
            info["path"] = str(self._db.path)
        return info

    def compact_db(self) -> dict:
        """Compaction like on start (prices/snapshots older than RETENTION_DAYS) + VACUUM."""
        try:
            store = Storage(self._db.path)
            before = store.db_info()["size"]
            cutoff = int((time.time() - config.RETENTION_DAYS * 86400) * 1000)
            removed = store.compact(cutoff, config.COMPACT_BUCKET_MS)
            store.vacuum()
            after = store.db_info()["size"]
            store.close()
        except Exception as exc:  # e.g. database busy
            log.exception("compaction failed")
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "prices": removed[0], "snaps": removed[1], "before": before, "after": after}

    def about(self) -> dict:
        return {"version": __version__, "python": platform.python_version(),
                "github": f"https://github.com/{config.GITHUB_REPO}",
                "libraries": [dict(name=n, version=_dist_version(d), license=lic, url=url)
                              for n, d, lic, url in LIBRARIES]}

    # ------------------------------------------------------------ setup wizard

    def wizard_state(self) -> dict:
        s = settings_mod.load()
        lang = s.language or get_language()
        set_language(lang)
        return {"lang": lang, "languages": LANGUAGES, "texts": texts(lang), "export_dir": str(s.export_path),
                "db_path": str(s.db_file), "first_run": not s.setup_done, "version": __version__}

    def wizard_language(self, lang: str) -> dict:
        if lang in LANGUAGES:
            set_language(lang)
        return texts(get_language())

    def wizard_finish(self, values: dict) -> dict:
        """Save the wizard; the page shows a possible warning and then calls wizard_open."""
        current = settings_mod.load()
        export_dir = Path(values.get("export_dir") or current.export_path)
        warning = self._enable_mods(export_dir, bool(values.get("enable_mods")))
        lang = values.get("language") if values.get("language") in LANGUAGES else get_language()
        new = replace(current, language=lang, export_dir=str(export_dir),
                      db_path=str(values.get("db_path") or current.db_file), setup_done=True)
        settings_mod.save(new)
        set_language(lang)
        return {"warning": warning}

    def wizard_open(self) -> dict:
        """Start recording and automation, then show the app in the same window. {"error"} if that failed."""
        try:
            self._open_app()
        except sqlite3.OperationalError as exc:
            log.exception("opening the database after the wizard failed")
            return {"error": t("app.db_error", error=exc)}
        return {}

    def wizard_cancel(self) -> None:
        """First start: quit. Re-run via --setup: continue with the unchanged settings."""
        if not settings_mod.load().setup_done:
            self._close_window()
            return
        set_language(settings_mod.load().language or get_language())
        self._open_app()
