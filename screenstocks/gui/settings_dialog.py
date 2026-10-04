"""Settings dialog with tabs (General, Colours, Data, Updates).

The setup wizard is only used for the first start; afterwards everything is
changed here. Colours and the update switch apply immediately, language and
folders after a restart.
"""

import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from .. import __version__, config, settings as settings_mod
from ..i18n import LANGUAGES, get_language, set_language, t
from ..storage import Storage
from . import fmt
from .theme import THEME

if TYPE_CHECKING:
    from .app import App


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.current = app.settings
        self.title(t("settings.title"))
        self.configure(bg=THEME["panel"])
        self.transient(app)
        self.resizable(False, False)

        self.lang_var = tk.StringVar(value=self.current.language or get_language())
        self.export_var = tk.StringVar(value=str(self.current.export_path))
        self.db_var = tk.StringVar(value=str(self.current.db_file))
        self.enable_mods_var = tk.BooleanVar(value=True)
        self.updates_var = tk.BooleanVar(value=self.current.check_updates)
        self.colors = dict(self.current.stock_colors)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        for builder, key in ((self._tab_general, "settings.tab_general"), (self._tab_colors, "settings.tab_colors"),
                             (self._tab_data, "settings.tab_data"), (self._tab_updates, "settings.tab_updates")):
            frame = ttk.Frame(nb, style="Panel.TFrame", padding=(16, 12))
            builder(frame)
            nb.add(frame, text=f"  {t(key)}  ")

        buttons = ttk.Frame(self, style="Panel.TFrame", padding=(10, 10))
        buttons.pack(fill="x")
        ttk.Button(buttons, text=t("settings.save"), style="Accent.TButton", command=self._save).pack(side="right")
        ttk.Button(buttons, text=t("setup.cancel"), command=self.destroy).pack(side="right", padx=6)

        self.update_idletasks()
        w, h = max(self.winfo_reqwidth(), 700), max(self.winfo_reqheight(), 480)
        x = app.winfo_rootx() + (app.winfo_width() - w) // 2
        y = app.winfo_rooty() + (app.winfo_height() - h) // 3
        self.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()

    # ---------------------------------------------------------------- general

    def _tab_general(self, f: ttk.Frame) -> None:
        ttk.Label(f, text=t("setup.done.language"), style="Section.TLabel").pack(anchor="w")
        row = ttk.Frame(f, style="Panel.TFrame")
        row.pack(anchor="w", pady=(2, 12))
        for code, name in LANGUAGES.items():
            ttk.Radiobutton(row, text=name, value=code, variable=self.lang_var).pack(side="left", padx=(0, 16))

        ttk.Label(f, text=t("setup.done.export"), style="Section.TLabel").pack(anchor="w")
        row = ttk.Frame(f, style="Panel.TFrame")
        row.pack(fill="x", pady=(2, 2))
        entry = ttk.Entry(row, textvariable=self.export_var, width=70)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<FocusOut>", lambda e: self._check_export())
        ttk.Button(row, text=t("setup.game.browse"), command=self._browse_export).pack(side="left", padx=(6, 0))
        ttk.Button(row, text=t("setup.game.detect"), command=self._detect_export).pack(side="left", padx=(6, 0))
        self.export_checks = ttk.Frame(f, style="Panel.TFrame")
        self.export_checks.pack(fill="x", pady=(0, 12))
        self._check_export()

        ttk.Label(f, text=t("setup.done.db"), style="Section.TLabel").pack(anchor="w")
        row = ttk.Frame(f, style="Panel.TFrame")
        row.pack(fill="x", pady=(2, 2))
        ttk.Entry(row, textvariable=self.db_var, width=70).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text=t("setup.game.browse"), command=self._browse_db).pack(side="left", padx=(6, 0))
        ttk.Label(f, text=t("settings.restart_note"), style="Muted.TLabel").pack(anchor="w", pady=(12, 0))

    def _check_export(self) -> None:
        for w in self.export_checks.winfo_children():
            w.destroy()
        path = Path(self.export_var.get())
        ok = path.is_dir()
        ttk.Label(self.export_checks, text=t("setup.game.dir_ok") if ok else t("setup.game.dir_missing"),
                  style="Ok.TLabel" if ok else "Bad.TLabel").pack(anchor="w")
        if ok:
            found = (path / config.MARKET_FILE).exists()
            ttk.Label(self.export_checks, text=t("setup.game.market_ok") if found else t("setup.game.market_missing"),
                      style="Ok.TLabel" if found else "Warn.TLabel").pack(anchor="w")
        mods = settings_mod.read_mod_settings(path)
        if mods is not None and not (mods.get("export") and mods.get("commands")):
            ttk.Label(self.export_checks, text=t("setup.game.mods_flags", export=mods.get("export"),
                                                 commands=mods.get("commands")), style="Warn.TLabel").pack(anchor="w")
            ttk.Checkbutton(self.export_checks, text=t("setup.game.enable_mods"),
                            variable=self.enable_mods_var).pack(anchor="w")

    def _browse_export(self) -> None:
        start = self.export_var.get()
        path = filedialog.askdirectory(title=t("setup.game.select_title"), parent=self,
                                       initialdir=start if Path(start).is_dir() else None)
        if path:
            self.export_var.set(str(settings_mod.normalize_export_dir(Path(path))))
            self._check_export()

    def _detect_export(self) -> None:
        found = settings_mod.detect_export_dir()
        if found:
            self.export_var.set(str(found))
        else:
            messagebox.showinfo(t("settings.title"), t("setup.game.detect_failed"), parent=self)
        self._check_export()

    def _browse_db(self) -> None:
        current = Path(self.db_var.get())
        path = filedialog.asksaveasfilename(
            title=t("setup.data.select_title"), parent=self, defaultextension=".db",
            initialdir=str(current.parent), initialfile=current.name, confirmoverwrite=False,
            filetypes=[("SQLite", "*.db"), ("*", "*.*")])
        if path:
            self.db_var.set(str(Path(path)))

    # ----------------------------------------------------------------- colors

    def _tab_colors(self, f: ttk.Frame) -> None:
        ttk.Label(f, text=t("settings.colors_text"), style="Body.TLabel", wraplength=640,
                  justify="left").pack(anchor="w", pady=(0, 10))
        self.color_grid = ttk.Frame(f, style="Panel.TFrame")
        self.color_grid.pack(anchor="w")
        ttk.Button(f, text=t("settings.colors_reset"), command=self._reset_colors).pack(anchor="w", pady=(12, 0))
        self._render_colors()

    def _stock_ids(self) -> list[str]:
        ctx = self.app._ctx
        ids = {s["stock_id"] for s in ctx.stocks} if ctx else set()
        return sorted(ids | set(self.colors))

    def _render_colors(self) -> None:
        for w in self.color_grid.winfo_children():
            w.destroy()
        for i, sid in enumerate(self._stock_ids()):
            r, c = divmod(i, 2)
            color = self.colors.get(sid, THEME["muted"])
            ttk.Label(self.color_grid, text=sid, style="Body.TLabel", width=12).grid(row=r, column=c * 2,
                                                                                  sticky="w", pady=3)
            tk.Button(self.color_grid, text=color, width=10, bg=color, fg="#0d1117", activebackground=color,
                      relief="flat", bd=0, cursor="hand2", font=THEME["font_small_bold"],
                      command=lambda s=sid: self._pick_color(s)).grid(row=r, column=c * 2 + 1, sticky="w",
                                                                      padx=(0, 40), pady=3)

    def _pick_color(self, sid: str) -> None:
        _rgb, hex_color = colorchooser.askcolor(color=self.colors.get(sid), parent=self,
                                                title=t("settings.pick_color", stock=sid))
        if hex_color:
            self.colors[sid] = hex_color
            self._render_colors()

    def _reset_colors(self) -> None:
        self.colors = settings_mod.default_colors(self._stock_ids())
        self._render_colors()

    # ------------------------------------------------------------------- data

    def _tab_data(self, f: ttk.Frame) -> None:
        ttk.Label(f, text=t("settings.data_text", days=config.RETENTION_DAYS, s=config.COMPACT_BUCKET_MS // 1000),
                  style="Body.TLabel", wraplength=640, justify="left").pack(anchor="w", pady=(0, 10))
        self.data_info = ttk.Label(f, text="", style="Muted.TLabel", justify="left")
        self.data_info.pack(anchor="w", pady=(0, 10))
        self.compact_btn = ttk.Button(f, text=t("settings.compact_now"), command=self._compact)
        self.compact_btn.pack(anchor="w")
        self.compact_status = ttk.Label(f, text="", style="Ok.TLabel", wraplength=640, justify="left")
        self.compact_status.pack(anchor="w", pady=(8, 0))
        self._show_db_info()

    def _show_db_info(self) -> None:
        info = self.app.db.db_info()
        self.data_info.configure(text=t(
            "settings.data_info", path=self.app.db.path, size=fmt.num(info["size"] / 1e6, 1),
            prices=fmt.num(info["prices"], 0), snaps=fmt.num(info["snapshots"], 0),
            oldest=fmt.clock(info["oldest_ms"], with_date=True)))

    def _compact(self) -> None:
        self.compact_btn.configure(state="disabled")
        self.compact_status.configure(text=t("settings.compacting"), style="Warn.TLabel")
        db_path = self.app.db.path

        def work() -> None:
            try:
                store = Storage(db_path)
                before = store.db_info()["size"]
                cutoff = int((time.time() - config.RETENTION_DAYS * 86400) * 1000)
                removed = store.compact(cutoff, config.COMPACT_BUCKET_MS)
                store.vacuum()
                after = store.db_info()["size"]
                store.close()
                msg = t("settings.compact_done", prices=fmt.num(removed[0], 0), snaps=fmt.num(removed[1], 0),
                        before=fmt.num(before / 1e6, 1), after=fmt.num(after / 1e6, 1))
                style = "Ok.TLabel"
            except Exception as exc:  # e.g. database busy
                msg, style = t("common.error", error=exc), "Bad.TLabel"
            self.after(0, lambda: self._compact_done(msg, style))

        threading.Thread(target=work, daemon=True).start()

    def _compact_done(self, msg: str, style: str) -> None:
        if not self.winfo_exists():
            return
        self.compact_btn.configure(state="normal")
        self.compact_status.configure(text=msg, style=style)
        self._show_db_info()

    # ---------------------------------------------------------------- updates

    def _tab_updates(self, f: ttk.Frame) -> None:
        ttk.Label(f, text=t("settings.version", version=__version__), style="Section.TLabel").pack(anchor="w")
        ttk.Checkbutton(f, text=t("settings.check_on_start"), variable=self.updates_var).pack(anchor="w",
                                                                                              pady=(10, 10))
        ttk.Button(f, text=t("settings.check_now"), command=self._check_now).pack(anchor="w")
        self.update_status = ttk.Label(f, text="", style="Muted.TLabel", wraplength=640, justify="left")
        self.update_status.pack(anchor="w", pady=(8, 0))

    def _check_now(self) -> None:
        self.update_status.configure(text=t("update.checking"), style="Muted.TLabel")

        def done(release, error) -> None:
            if not self.winfo_exists():
                return
            if error:
                self.update_status.configure(text=t("update.failed", error=error), style="Bad.TLabel")
            elif release is None:
                self.update_status.configure(text=t("update.up_to_date", version=__version__), style="Ok.TLabel")
            else:
                self.update_status.configure(text=t("update.available", version=release.version), style="Warn.TLabel")

        self.app.check_for_updates(manual=True, callback=done)

    # ------------------------------------------------------------------- save

    def _save(self) -> None:
        export_dir = Path(self.export_var.get())
        mods = settings_mod.read_mod_settings(export_dir)
        if mods is not None and self.enable_mods_var.get() and not (mods.get("export") and mods.get("commands")):
            try:
                settings_mod.enable_mod_features(export_dir)
            except OSError as exc:
                messagebox.showwarning(t("settings.title"), t("setup.mods_write_failed", error=exc), parent=self)
        new = replace(self.current, language=self.lang_var.get(), export_dir=str(export_dir),
                      db_path=self.db_var.get(), check_updates=self.updates_var.get(),
                      stock_colors=dict(self.colors))
        needs_restart = (new.language != (self.current.language or get_language())
                         or Path(new.export_dir) != self.current.export_path
                         or Path(new.db_path) != self.current.db_file)
        settings_mod.save(new)
        self.app.apply_settings(new)
        if needs_restart:
            ui_lang = get_language()
            set_language(new.language)          # ask in the newly chosen language
            restart = messagebox.askyesno(t("settings.title"), t("setup.restart"), parent=self)
            set_language(ui_lang)
            self.destroy()
            if restart:
                self.app.restart()
        else:
            self.destroy()
