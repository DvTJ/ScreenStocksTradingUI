"""First-run setup wizard (also reachable later via "⚙ Settings").

Steps: language -> game export folder (+ mod-settings.json) -> database -> summary.
"""

import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from .. import config, settings as settings_mod
from ..i18n import LANGUAGES, get_language, set_language, t
from ..settings import Settings
from .theme import THEME, apply_style, set_window_icon


class SetupWizard(ttk.Frame):
    STEPS = ("language", "game", "data", "done")

    def __init__(self, master: tk.Misc, current: Settings, on_finish: Callable[[Settings], None],
                 on_cancel: Callable[[], None]):
        super().__init__(master, style="Panel.TFrame", padding=(24, 18))
        self.on_finish, self.on_cancel = on_finish, on_cancel
        self.current = current
        self.step = 0
        self.lang_var = tk.StringVar(value=current.language or get_language())
        self.export_var = tk.StringVar(value=str(current.export_path))
        self.db_var = tk.StringVar(value=str(current.db_file))
        self.enable_mods_var = tk.BooleanVar(value=True)
        set_language(self.lang_var.get())

        self.body = ttk.Frame(self, style="Panel.TFrame")
        self.body.pack(fill="both", expand=True)
        nav = ttk.Frame(self, style="Panel.TFrame")
        nav.pack(fill="x", pady=(16, 0))
        self.step_label = ttk.Label(nav, style="Muted.TLabel")
        self.step_label.pack(side="left")
        self.next_btn = ttk.Button(nav, style="Accent.TButton", command=self._next)
        self.next_btn.pack(side="right")
        self.back_btn = ttk.Button(nav, command=self._back)
        self.back_btn.pack(side="right", padx=6)
        self.cancel_btn = ttk.Button(nav, command=self.on_cancel)
        self.cancel_btn.pack(side="right", padx=(0, 18))
        self._render()

    # ------------------------------------------------------------- navigation

    def _render(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        getattr(self, f"_page_{self.STEPS[self.step]}")()
        last = self.step == len(self.STEPS) - 1
        self.step_label.configure(text=t("setup.step", n=self.step + 1, total=len(self.STEPS)))
        self.next_btn.configure(text=t("setup.finish") if last else t("setup.next"))
        self.back_btn.configure(text=t("setup.back"), state="normal" if self.step else "disabled")
        self.cancel_btn.configure(text=t("setup.cancel"))
        self.winfo_toplevel().title(t("setup.title"))

    def _back(self) -> None:
        if self.step:
            self.step -= 1
            self._render()

    def _next(self) -> None:
        name = self.STEPS[self.step]
        if name == "game" and not Path(self.export_var.get()).is_dir():
            if not messagebox.askyesno(t("setup.title"), t("setup.game.continue_anyway"), parent=self):
                return
        if self.step < len(self.STEPS) - 1:
            self.step += 1
            self._render()
        else:
            self._finish()

    def _finish(self) -> None:
        export_dir = Path(self.export_var.get())
        mods = settings_mod.read_mod_settings(export_dir)
        if mods is not None and self.enable_mods_var.get() and not (mods.get("export") and mods.get("commands")):
            try:
                settings_mod.enable_mod_features(export_dir)
            except OSError as exc:
                messagebox.showwarning(t("setup.title"), t("setup.mods_write_failed", error=exc), parent=self)
        # keep options the wizard does not show (colours, update check, ...)
        self.on_finish(replace(self.current, language=self.lang_var.get(), export_dir=str(export_dir),
                               db_path=self.db_var.get(), setup_done=True))

    # ------------------------------------------------------------------ pages

    def _heading(self, key_heading: str, key_text: str) -> None:
        ttk.Label(self.body, text=t(key_heading), style="Heading.TLabel").pack(anchor="w")
        ttk.Label(self.body, text=t(key_text), style="Body.TLabel", wraplength=560,
                  justify="left").pack(anchor="w", pady=(6, 16))

    def _page_language(self) -> None:
        self._heading("setup.lang.heading", "setup.lang.text")
        for code, name in LANGUAGES.items():
            ttk.Radiobutton(self.body, text=name, value=code, variable=self.lang_var,
                            command=self._on_language).pack(anchor="w", pady=3, padx=8)

    def _on_language(self) -> None:
        set_language(self.lang_var.get())
        self._render()

    def _page_game(self) -> None:
        self._heading("setup.game.heading", "setup.game.text")
        row = ttk.Frame(self.body, style="Panel.TFrame")
        row.pack(fill="x")
        entry = ttk.Entry(row, textvariable=self.export_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<FocusOut>", lambda e: self._check_game())
        ttk.Button(row, text=t("setup.game.browse"), command=self._browse_export).pack(side="left", padx=(6, 0))
        ttk.Button(row, text=t("setup.game.detect"), command=self._detect_export).pack(side="left", padx=(6, 0))
        self.game_checks = ttk.Frame(self.body, style="Panel.TFrame")
        self.game_checks.pack(fill="x", pady=(12, 0))
        self._check_game()

    def _check_game(self) -> None:
        for w in self.game_checks.winfo_children():
            w.destroy()
        path = Path(self.export_var.get())
        lines = [("setup.game.dir_ok", "Ok") if path.is_dir() else ("setup.game.dir_missing", "Bad")]
        if path.is_dir():
            lines.append(("setup.game.market_ok", "Ok") if (path / config.MARKET_FILE).exists()
                         else ("setup.game.market_missing", "Warn"))
        for key, style in lines:
            ttk.Label(self.game_checks, text=t(key), style=f"{style}.TLabel", wraplength=560,
                      justify="left").pack(anchor="w", pady=1)
        mods = settings_mod.read_mod_settings(path)
        if mods is None:
            if path.is_dir():
                ttk.Label(self.game_checks, text=t("setup.game.mods_missing"), style="Warn.TLabel").pack(anchor="w")
            return
        ok = bool(mods.get("export")) and bool(mods.get("commands"))
        ttk.Label(self.game_checks, text=t("setup.game.mods_flags", export=mods.get("export"),
                                           commands=mods.get("commands")),
                  style="Ok.TLabel" if ok else "Warn.TLabel").pack(anchor="w", pady=1)
        if not ok:
            ttk.Checkbutton(self.game_checks, text=t("setup.game.enable_mods"),
                            variable=self.enable_mods_var).pack(anchor="w", pady=(6, 0))

    def _browse_export(self) -> None:
        start = self.export_var.get()
        path = filedialog.askdirectory(title=t("setup.game.select_title"), parent=self,
                                       initialdir=start if Path(start).is_dir() else None)
        if path:
            self.export_var.set(str(settings_mod.normalize_export_dir(Path(path))))
            self._check_game()

    def _detect_export(self) -> None:
        found = settings_mod.detect_export_dir()
        if found:
            self.export_var.set(str(found))
        else:
            messagebox.showinfo(t("setup.title"), t("setup.game.detect_failed"), parent=self)
        self._check_game()

    def _page_data(self) -> None:
        self._heading("setup.data.heading", "setup.data.text")
        ttk.Label(self.body, text=t("setup.data.file"), style="Section.TLabel").pack(anchor="w")
        row = ttk.Frame(self.body, style="Panel.TFrame")
        row.pack(fill="x", pady=(4, 0))
        ttk.Entry(row, textvariable=self.db_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text=t("setup.game.browse"), command=self._browse_db).pack(side="left", padx=(6, 0))
        exists = Path(self.db_var.get()).exists()
        ttk.Label(self.body, text=t("setup.data.exists") if exists else t("setup.data.new"),
                  style="Ok.TLabel" if exists else "Muted.TLabel").pack(anchor="w", pady=(10, 0))

    def _browse_db(self) -> None:
        current = Path(self.db_var.get())
        path = filedialog.asksaveasfilename(
            title=t("setup.data.select_title"), parent=self, defaultextension=".db",
            initialdir=str(current.parent), initialfile=current.name,
            confirmoverwrite=False, filetypes=[("SQLite", "*.db"), ("*", "*.*")])
        if path:
            self.db_var.set(str(Path(path)))
            self._render()

    def _page_done(self) -> None:
        self._heading("setup.done.heading", "setup.done.text")
        grid = ttk.Frame(self.body, style="Panel.TFrame")
        grid.pack(fill="x")
        rows = (("setup.done.language", LANGUAGES.get(self.lang_var.get(), self.lang_var.get())),
                ("setup.done.export", self.export_var.get()),
                ("setup.done.db", self.db_var.get()))
        for i, (key, value) in enumerate(rows):
            ttk.Label(grid, text=t(key), style="Muted.TLabel").grid(row=i, column=0, sticky="nw", padx=(0, 16), pady=2)
            ttk.Label(grid, text=value, style="Body.TLabel", wraplength=430).grid(row=i, column=1, sticky="w", pady=2)
        ttk.Label(self.body, text=t("setup.done.note"), style="Warn.TLabel", wraplength=560,
                  justify="left").pack(anchor="w", pady=(18, 0))


def _center(win: tk.Misc, width: int, height: int) -> None:
    win.update_idletasks()
    x = (win.winfo_screenwidth() - width) // 2
    y = (win.winfo_screenheight() - height) // 3
    win.geometry(f"{width}x{height}+{x}+{y}")


def run_setup(current: Settings) -> Optional[Settings]:
    """Standalone wizard before the main window exists. Returns None if cancelled."""
    result: list[Optional[Settings]] = [None]
    root = tk.Tk()
    root.configure(bg=THEME["panel"])
    apply_style(root)
    set_window_icon(root)
    root.resizable(False, False)

    def finish(s: Settings) -> None:
        settings_mod.save(s)
        result[0] = s
        root.destroy()

    SetupWizard(root, current, finish, root.destroy).pack(fill="both", expand=True)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    _center(root, 680, 470)
    root.mainloop()
    return result[0]


def open_settings_dialog(parent: tk.Tk, on_restart: Callable[[], None]) -> None:
    """Re-run the wizard from the running app; changes apply after a restart."""
    current = settings_mod.load()
    if not current.language:
        current = replace(current, language=get_language())
    lang_before = get_language()
    win = tk.Toplevel(parent)
    win.configure(bg=THEME["panel"])
    win.transient(parent)
    win.resizable(False, False)

    def close() -> None:
        set_language(lang_before)  # the running UI keeps its language until restart
        win.destroy()

    def finish(s: Settings) -> None:
        settings_mod.save(s)
        restart = messagebox.askyesno(t("setup.title"), t("setup.restart"), parent=win)  # in the new language
        close()
        if restart:
            on_restart()

    SetupWizard(win, current, finish, close).pack(fill="both", expand=True)
    win.protocol("WM_DELETE_WINDOW", close)
    _center(win, 680, 470)
    win.grab_set()
