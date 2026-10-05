"""The Bot tab: on/off switch, level, status sentence, results, positions and a plain-language journal."""

import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from .. import bot
from ..i18n import t
from . import fmt
from .theme import THEME
from .widgets import SortableTree, scrolled

if TYPE_CHECKING:
    from .app import Ctx

PARAMS = tuple(bot.Params.__dataclass_fields__)      # advanced fields, in display order
STEP = {"entry_z": 0.1, "exit_z": 0.1, "min_edge_pct": 0.5, "stop_pct": 1, "tau_s": 10, "max_hold_s": 10, "confirm_s": 1, "max_loss_pct": 0.5, "jump_pct": 1, "news_s": 5}


class Tip:
    """A small round "i" label; hovering it shows `text` in a floating box."""

    def __init__(self, parent, text: str):
        self.text, self.win = text, None
        self.label = tk.Label(parent, text=" i ", bg=THEME["panel_alt"], fg=THEME["muted"], cursor="question_arrow",
                              font=(THEME["font_bold"][0], 8, "bold italic"), bd=1, relief="solid")
        self.label.bind("<Enter>", self._show)
        self.label.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        self.win = tk.Toplevel(self.label)
        self.win.wm_overrideredirect(True)
        self.win.wm_geometry(f"+{self.label.winfo_rootx() + 14}+{self.label.winfo_rooty() + 22}")
        tk.Label(self.win, text=self.text, justify="left", wraplength=320, bg=THEME["panel"], fg=THEME["fg"], bd=1,
                 relief="solid", padx=8, pady=6).pack()

    def _hide(self, _event=None):
        if self.win:
            self.win.destroy()
            self.win = None


class BotTab(ttk.Frame):
    POSITION_COLUMNS = [
        ("stock", "common.stock", 90, "w"),
        ("side", "bot.col_side", 80, "w"),
        ("entry", "bot.col_entry", 100, "e"),
        ("target", "bot.col_target", 100, "e"),
        ("gain", "bot.col_gain", 100, "e"),
    ]
    LOG_COLUMNS = [
        ("time", "common.time", 130, "w"),
        ("msg", "auto.col_message", 900, "w"),
    ]

    def __init__(self, master, app):
        super().__init__(master, style="Panel.TFrame")
        self.app = app
        s = bot.load_settings(app.db)
        self.enabled = tk.BooleanVar(value=s.enabled)
        self.shorts = tk.BooleanVar(value=s.shorts)
        self.paper = tk.BooleanVar(value=s.paper)
        self.trade_events = tk.BooleanVar(value=s.trade_events)
        self.level = tk.StringVar()
        self.caution = tk.StringVar()
        self.trade_pct = tk.StringVar()
        self.max_positions = tk.StringVar()
        self.recalib = tk.StringVar()
        self.loss_limit = tk.StringVar()
        self.params = {k: tk.StringVar() for k in PARAMS}
        self.stock_vars: dict[str, tk.BooleanVar] = {}      # checked = the bot may trade it
        self.spins: dict[str, tk.Spinbox] = {}
        self.marks: dict[str, ttk.Label] = {}
        self.shown: dict[str, float] = {}                   # advanced values as last displayed
        self.adv_open = False

        card = ttk.Frame(self, style="Card.TFrame", padding=(10, 8))
        card.pack(fill="x", padx=4, pady=(8, 4))
        card.columnconfigure(0, weight=1)
        head = ttk.Frame(card, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        self._check(head, t("bot.enable"), self.enabled).pack(side="left", padx=(0, 16))
        self._check(head, t("bot.paper"), self.paper).pack(side="left", padx=(0, 4))
        Tip(head, t("bot.d.paper")).label.pack(side="left", padx=(0, 8))
        tk.Label(head, text=f" {t('bot.experimental_badge')} ", bg=THEME["warn"], fg="#000000", font=THEME["font_bold"]).pack(side="left", padx=(0, 16))
        ttk.Label(head, text=t("bot.level"), style="CardMuted.TLabel").pack(side="left", padx=(0, 4))
        self.level_box = self._combo(head, self.level, [t(f"bot.level.{k}") for k in bot.LEVELS], self._on_level)
        self.level_box.pack(side="left", padx=(0, 16))
        self.state = ttk.Label(head, text="", style="CardValue.TLabel")
        self.state.pack(side="left", padx=8)
        ttk.Button(head, text=t("bot.import"), command=self._import_setup).pack(side="right")
        ttk.Button(head, text=t("bot.export"), command=self._export_setup).pack(side="right", padx=6)

        self.row_simple = ttk.Frame(card, style="Card.TFrame")
        self.row_simple.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._field(self.row_simple, "bot.trade_pct", self.trade_pct, "trade_pct", 1, 100, 1)
        ttk.Label(self.row_simple, text=t("bot.d.trade_pct"), style="CardMuted.TLabel").pack(side="left", padx=8)

        self.row_medium = ttk.Frame(card, style="Card.TFrame")
        self.row_medium.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(self.row_medium, text=t("bot.caution"), style="CardMuted.TLabel").pack(side="left", padx=(0, 4))
        self.caution_box = self._combo(self.row_medium, self.caution,
                                       [t(f"bot.caution.{k}") for k in bot.PRESETS], self._on_caution)
        self.caution_box.pack(side="left", padx=(0, 4))
        Tip(self.row_medium, t("bot.d.caution")).label.pack(side="left", padx=(0, 16))
        self._field(self.row_medium, "bot.max_positions", self.max_positions, "max_positions", 1, 10, 1)
        self._check(self.row_medium, t("bot.shorts"), self.shorts).pack(side="left", padx=(16, 4))
        Tip(self.row_medium, t("bot.d.shorts")).label.pack(side="left")
        self._check(self.row_medium, t("bot.trade_events"), self.trade_events).pack(side="left", padx=(16, 4))
        Tip(self.row_medium, t("bot.d.trade_events")).label.pack(side="left")

        self.adv_btn = ttk.Button(card, command=self._toggle_adv)
        self.adv_btn.grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.adv = ttk.Frame(card, style="Card.TFrame")
        self.adv.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        extra = {"recalib_min": (self.recalib, 1, 1), "loss_limit_pct": (self.loss_limit, 0, 1)}   # var, min, step
        for i, k in enumerate((*PARAMS, *extra)):
            var, lo, step = extra[k] if k in extra else (self.params[k], 0, STEP[k])
            ttk.Label(self.adv, text=t(f"bot.p.{k}"), style="CardValue.TLabel").grid(row=i, column=0, sticky="w", padx=(0, 8))
            spin = self._spin(self.adv, var, k, lo, 100000, step)
            spin.grid(row=i, column=1, sticky="w")
            self.marks[k] = ttk.Label(self.adv, text="", style="CardMuted.TLabel", width=8)
            self.marks[k].grid(row=i, column=2, padx=6)
            Tip(self.adv, t(f"bot.d.{k}")).label.grid(row=i, column=3, sticky="w")
        n = len(PARAMS) + len(extra)
        ttk.Button(self.adv, text=t("bot.reset_auto"), command=self._reset_auto).grid(row=n, column=0, sticky="w", pady=6)
        ttk.Label(self.adv, text=t("bot.stocks_traded"), style="CardValue.TLabel").grid(row=n + 1, column=0, sticky="w")
        self.stock_frame = ttk.Frame(self.adv, style="Card.TFrame")
        self.stock_frame.grid(row=n + 1, column=1, columnspan=3, sticky="w")

        self.bind("<Map>", self._warn_once)
        rf = ttk.Frame(self, style="Panel.TFrame")
        rf.pack(fill="x", padx=8, pady=(4, 2))
        ttk.Button(rf, text=t("bot.trades_detail"), command=self._show_trades).pack(side="right")
        ttk.Button(rf, text=t("bot.clear"), command=self._clear_history).pack(side="right", padx=6)
        self.results = ttk.Label(rf, text="", style="Section.TLabel", wraplength=1200, justify="left")
        self.results.pack(side="left", anchor="w")

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, pady=(4, 0))
        posf = ttk.Frame(paned, style="Panel.TFrame")
        ttk.Label(posf, text=t("bot.positions"), style="Section.TLabel").pack(anchor="w", padx=4, pady=(4, 2))
        f, self.pos_tree = scrolled(posf, lambda m: SortableTree(m, self.POSITION_COLUMNS, height=4))
        f.pack(fill="both", expand=True)
        self.pos_tree.tag_configure("up", foreground=THEME["up"])
        self.pos_tree.tag_configure("down", foreground=THEME["down"])
        paned.add(posf, weight=1)
        logf = ttk.Frame(paned, style="Panel.TFrame")
        ttk.Label(logf, text=t("bot.log"), style="Section.TLabel").pack(anchor="w", padx=4, pady=(6, 2))
        f, self.log_tree = scrolled(logf, lambda m: SortableTree(m, self.LOG_COLUMNS, height=8))
        f.pack(fill="both", expand=True)
        self.log_tree.sort_col, self.log_tree.sort_desc = "time", True
        paned.add(logf, weight=3)
        thinkf = ttk.Frame(paned, style="Panel.TFrame")
        th = ttk.Frame(thinkf, style="Panel.TFrame")
        th.pack(fill="x")
        ttk.Label(th, text=t("bot.thinking"), style="Section.TLabel").pack(side="left", padx=4, pady=(6, 2))
        self.think_status = ttk.Label(th, text="", style="CardMuted.TLabel")
        self.think_status.pack(side="left", padx=12)
        ttk.Button(th, text=t("bot.export_results"), command=lambda: self._export_results(self)).pack(side="right", padx=4)
        ttk.Button(th, text=t("bot.copy"), command=self._copy_thoughts).pack(side="right")
        f, self.think_tree = scrolled(thinkf, lambda m: SortableTree(m, self.LOG_COLUMNS, height=8))
        f.pack(fill="both", expand=True)
        self.think_tree.sort_col, self.think_tree.sort_desc = "time", True
        self.think_tree.bind("<Double-1>", self._open_event_page)
        paned.add(thinkf, weight=3)

        bt = ttk.Frame(self, style="Card.TFrame", padding=(10, 6))
        bt.pack(fill="x", padx=4, pady=(4, 4))
        ttk.Label(bt, text=t("bot.test.capital"), style="CardMuted.TLabel").pack(side="left", padx=(0, 4))
        cash = (app.db.latest_snapshot() or {}).get("cash")
        self.capital = tk.StringVar(value=f"{round(cash) if cash else 10000}")
        self.capital_spin = self._spin(bt, self.capital, "capital", 1, 10**12, 1000)
        self.capital_spin.pack(side="left", padx=(0, 8))
        self.use_cash = tk.BooleanVar(value=True)
        self._check(bt, t("bot.test.use_cash"), self.use_cash, self._toggle_cash).pack(side="left", padx=(0, 12))
        self._toggle_cash()
        self.range_var = tk.StringVar(value="all")
        ttk.Combobox(bt, textvariable=self.range_var, width=5, state="readonly",
                     values=list(bot.TEST_RANGES)).pack(side="left", padx=(0, 8))
        self.bt_btn = ttk.Button(bt, text=t("bot.test"), command=self._run_test)
        self.bt_btn.pack(side="left", padx=(0, 6))
        self.detail_btn = ttk.Button(bt, text=t("bot.test.detail"), command=self._show_detail, state="disabled")
        self.detail_btn.pack(side="left", padx=(0, 12))
        self.last_test = None
        self.bt_result = ttk.Label(bt, text="", style="CardMuted.TLabel", wraplength=1100, justify="left")
        self.bt_result.pack(side="left", fill="x", expand=True)
        self.load()

    # ---------------------------------------------------------------- widgets

    @staticmethod
    def _check(parent, text, var, command=None):
        return tk.Checkbutton(parent, text=text, variable=var, command=command, bg=THEME["panel_alt"],
                              fg=THEME["fg"], selectcolor=THEME["panel"], activebackground=THEME["panel_alt"],
                              activeforeground=THEME["fg"], font=THEME["font_bold"], highlightthickness=0, bd=0)

    def _combo(self, parent, var, values, on_pick):
        box = ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=12)
        box.bind("<<ComboboxSelected>>", lambda e: on_pick())
        return box

    def _spin(self, parent, var, name, lo, hi, step):
        spin = tk.Spinbox(parent, from_=lo, to=hi, increment=step, width=6, textvariable=var, justify="right",
                          bg=THEME["panel"], fg=THEME["fg"], buttonbackground=THEME["panel_alt"],
                          insertbackground=THEME["fg"], relief="flat", command=self._save)
        spin.bind("<FocusOut>", lambda e: self._save())
        spin.bind("<Return>", lambda e: self._save())
        self.spins[name] = spin
        return spin

    def _field(self, parent, label_key, var, name, lo, hi, step):
        ttk.Label(parent, text=t(label_key), style="CardMuted.TLabel").pack(side="left", padx=(0, 4))
        self._spin(parent, var, name, lo, hi, step).pack(side="left")
        Tip(parent, t(f"bot.d.{name}")).label.pack(side="left", padx=(4, 0))

    # --------------------------------------------------------------- settings

    def load(self) -> None:
        """Re-read the stored settings into the widgets (also after a config import)."""
        s = bot.load_settings(self.app.db)
        self.enabled.set(s.enabled)
        self.shorts.set(s.shorts)
        self.paper.set(s.paper)
        self.trade_events.set(s.trade_events)
        self.level.set(t(f"bot.level.{s.level}"))
        self.caution.set(t(f"bot.caution.{s.caution}"))
        self.trade_pct.set(str(s.trade_pct))
        self.max_positions.set(str(s.max_positions))
        self.recalib.set(str(s.recalib_min))
        self.loss_limit.set(f"{s.loss_limit_pct:g}")
        self._fill_params(s, force=True)
        self._apply_level(s.level)

    def _fill_params(self, s: "bot.BotSettings", force: bool = False) -> None:
        """Advanced fields show the manual value or, failing that, what the calibration chose."""
        auto = bot.auto_params(self.app.engine.bot.calib, s)
        for k in PARAMS:
            manual = k in s.overrides
            self.marks[k].configure(text=t("bot.manual" if manual else "bot.auto"))
            if force or (not manual and self.focus_get() is not self.spins[k]):
                self.shown[k] = float(f"{s.overrides.get(k, auto[k]):g}")
                self.params[k].set(f"{self.shown[k]:g}")

    def _read(self) -> "bot.BotSettings":
        """Widgets -> settings; invalid numbers keep their stored value."""
        old = bot.load_settings(self.app.db)
        by_label = {t(f"bot.level.{k}"): k for k in bot.LEVELS}
        caution_by_label = {t(f"bot.caution.{k}"): k for k in bot.PRESETS}

        def num(var, cur, cast=int):
            try:
                return cast(float(str(var.get()).replace(",", ".")))
            except ValueError:
                return cur

        level = by_label.get(self.level.get(), old.level)
        caution = caution_by_label.get(self.caution.get(), old.caution)
        overrides = dict(old.overrides)
        for k in PARAMS:                       # a field that no longer shows what we put there was edited
            v = num(self.params[k], self.shown.get(k), float)
            if v is not None and v != self.shown.get(k) and (v > 0 or k == "exit_z"):
                overrides[k] = v
        return bot.BotSettings(
            enabled=bool(self.enabled.get()), paper=bool(self.paper.get()), trade_events=bool(self.trade_events.get()), level=level, trade_pct=num(self.trade_pct, old.trade_pct),
            caution=caution, max_positions=num(self.max_positions, old.max_positions),
            shorts=bool(self.shorts.get()), recalib_min=num(self.recalib, old.recalib_min),
            loss_limit_pct=num(self.loss_limit, old.loss_limit_pct, float),
            excluded=[sid for sid, v in self.stock_vars.items() if not v.get()] if self.stock_vars else old.excluded,
            overrides=overrides)

    def _save(self) -> None:
        s = self._read()
        if s != bot.load_settings(self.app.db):
            bot.save_settings(self.app.db, s)
        self._fill_params(s, force=True)
        self.trade_pct.set(str(s.trade_pct))
        self.max_positions.set(str(s.max_positions))
        self.recalib.set(str(s.recalib_min))
        self.loss_limit.set(f"{s.loss_limit_pct:g}")

    def _on_level(self) -> None:
        self._save()
        self._apply_level(bot.load_settings(self.app.db).level)

    def _on_caution(self) -> None:
        caution = next((k for k in bot.PRESETS if t(f"bot.caution.{k}") == self.caution.get()), "balanced")
        self.max_positions.set(str(bot.PRESETS[caution][1]))     # the preset's positions, still editable
        self._save()

    def _thoughts(self) -> list:
        """What the bot thinks, newest first (the order shown in the list and used by the copy button)."""
        return sorted(self.app.engine.bot.thoughts, key=lambda x: x[0], reverse=True)

    def _open_event_page(self, _event=None) -> None:
        """Double-click on an event thought: go to the Automation tab, where the events are listed."""
        sel = self.think_tree.selection()
        thoughts = self._thoughts()
        if not sel or not sel[0].isdigit() or int(sel[0]) >= len(thoughts) or not thoughts[int(sel[0])][3].startswith("event"):
            return
        nb = self.app.nb
        for i in range(nb.index("end")):
            if nb.tab(i, "text").strip() == t("tab.automation").strip():
                nb.select(i)

    def _copy_thoughts(self) -> None:
        lines = [f"{fmt.clock(ms, with_date=True)}  {msg}" for ms, _sid, msg, _code in self._thoughts()]
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        messagebox.showinfo(t("bot.thinking"), t("bot.copied"), parent=self)

    def _warn_once(self, _event=None) -> None:
        """The first time the tab is shown: the bot is experimental and can lose money."""
        if self.app.db.get_setting("bot_warning_ack", "") == "1":
            return
        self.app.db.set_setting("bot_warning_ack", "1")
        messagebox.showwarning(t("bot.experimental_title"), t("bot.experimental_text"), parent=self)

    def _export_setup(self) -> None:
        """Save the bot setup alone (switched off) so it can be shared."""
        self._save()
        path = filedialog.asksaveasfilename(parent=self, title=t("bot.export_title"), defaultextension=".json",
                                            filetypes=[("JSON", "*.json")], initialfile="screenstocks-bot.json")
        if path:
            self._file_action(t("bot.export_title"), lambda: bot.export_setup(self.app.db, path),
                              t("bot.exported", path=path), self, path=path)

    def _export_results(self, parent) -> None:
        """Save the history test (every trade with its real time) with the setup, calibration, live results
        and journal in one file to share."""
        path = filedialog.asksaveasfilename(parent=parent, title=t("bot.export_results_title"),
                                            defaultextension=".json", filetypes=[("JSON", "*.json")],
                                            initialfile="screenstocks-bot-report.json")
        if path:
            self._file_action(t("bot.export_results_title"),
                              lambda: bot.save_report(self.app.db, self.app.engine.bot.calib, self.last_test, path,
                                                      self.app.engine.bot.thoughts),
                              t("bot.results_exported", path=path), parent, path=path)

    def _import_setup(self) -> None:
        """Load the bot block of a shared file; the on/off switch keeps its current value."""
        path = filedialog.askopenfilename(parent=self, title=t("bot.import_title"), filetypes=[("JSON", "*.json")])
        if path and self._file_action(t("bot.import_title"), lambda: bot.import_setup(self.app.db, path),
                                      t("bot.imported"), self, invalid=True):
            self.load()

    @staticmethod
    def _file_action(title, action, done_text, parent, invalid=False, path=None) -> bool:
        try:
            action()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror(title, t("config.invalid" if invalid else "common.error", error=exc), parent=parent)
            return False
        if path:       # an exported file: offer to open its folder
            if messagebox.askyesno(title, f"{done_text}\n\n{t('bot.open_folder_ask')}", parent=parent):
                bot.reveal(path)
        else:
            messagebox.showinfo(title, done_text, parent=parent)
        return True

    def _toggle_adv(self) -> None:
        self.adv_open = not self.adv_open
        self._apply_level(bot.load_settings(self.app.db).level)

    def _apply_level(self, level: str) -> None:
        if level == "simple":
            self.row_medium.grid_remove()
        else:
            self.row_medium.grid()
        if level == "advanced":
            self.adv_btn.grid()
            self.adv_btn.configure(text=t("bot.advanced_open" if self.adv_open else "bot.advanced"))
            self.adv.grid() if self.adv_open else self.adv.grid_remove()
        else:
            self.adv_btn.grid_remove()
            self.adv.grid_remove()

    def _reset_auto(self) -> None:
        s = bot.load_settings(self.app.db)
        s.overrides = {}
        bot.save_settings(self.app.db, s)
        self._fill_params(s, force=True)

    def _sync_stock_checks(self, ctx: "Ctx", s: "bot.BotSettings") -> None:
        ids = [st["stock_id"] for st in ctx.stocks]
        if ids != list(self.stock_vars):
            for w in self.stock_frame.winfo_children():
                w.destroy()
            self.stock_vars = {sid: tk.BooleanVar(value=sid not in s.excluded) for sid in ids}
            for i, sid in enumerate(ids):
                self._check(self.stock_frame, sid, self.stock_vars[sid], self._save).grid(row=i // 8, column=i % 8,
                                                                                         sticky="w", padx=(0, 10))

    # ------------------------------------------------------------------- test

    def _capital(self) -> float:
        """Starting money: all the cash owned when the box is ticked, else the number typed in
        (spaces and decimal comma tolerated)."""
        cash = (self.app.db.latest_snapshot() or {}).get("cash")
        if self.use_cash.get() and cash:
            return float(cash)
        raw = "".join(c for c in self.capital.get().replace(",", ".") if c.isdigit() or c == ".")
        try:
            return max(1.0, float(raw))
        except ValueError:
            return float(cash or 10000)

    def _toggle_cash(self) -> None:
        """Ticked: the field shows (and is locked to) the cash currently owned."""
        if self.use_cash.get():
            cash = (self.app.db.latest_snapshot() or {}).get("cash")
            if cash:
                self.capital.set(f"{round(cash)}")
        self.capital_spin.configure(state="disabled" if self.use_cash.get() else "normal")

    def _run_test(self) -> None:
        self._save()
        s = bot.load_settings(self.app.db)
        self.bt_btn.state(["disabled"])
        self.bt_result.configure(text=t("bot.running"))
        path = self.app.db.path
        capital = self._capital()
        test_s = bot.TEST_RANGES[self.range_var.get()]

        def work():
            res = None
            try:
                text, res = bot.run_test(path, s, test_s, capital)
            except Exception as exc:
                text = t("common.error", error=exc)
            self.after(0, lambda: self._test_done(text, res))

        threading.Thread(target=work, daemon=True).start()

    def _test_done(self, text: str, res) -> None:
        self.bt_result.configure(text=text)
        self.bt_btn.state(["!disabled"])
        self.last_test = res if isinstance(res, dict) else None
        self.detail_btn.state(["!disabled"] if self.last_test else ["disabled"])

    def _clear_history(self) -> None:
        if messagebox.askyesno(t("bot.clear"), t("bot.clear_ask"), icon="warning", parent=self):
            bot.clear_history(self.app.db, self.app.engine.bot)
            messagebox.showinfo(t("bot.clear"), t("bot.cleared"), parent=self)

    def _show_trades(self) -> None:
        """Window with every trade of the current activation (real or practice), per-stock totals and CSV / JSON export."""
        res = bot.load_results(self.app.db)
        hist = bot.trade_history(res)
        win = tk.Toplevel(self)
        win.title(t("bot.trades.title"))
        win.geometry("1000x520")
        win.configure(bg=THEME["panel"])
        bar = ttk.Frame(win, style="Panel.TFrame")
        bar.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Button(bar, text=t("bot.export_results"), command=lambda: self._export_results(win)).pack(side="right")
        ttk.Button(bar, text=t("bot.trades.export_csv"), command=lambda: self._export_trades(win)).pack(side="right", padx=6)
        mode = t("bot.trades.practice") + "   " if bot.load_settings(self.app.db).paper else ""
        ttk.Label(bar, text=mode + t("bot.trades.summary", n=hist["n"], win=f"{hist['win_rate']:.0f}",
                                     profit=fmt.num(hist["profit"], 0)), style="Section.TLabel").pack(side="left")
        ttk.Label(win, text=t("bot.detail.per_stock") + ":  " + "   ".join(
            f"{sid}: {v['n']}× {fmt.num(v['profit'], 0)}" for sid, v in sorted(hist["per_stock"].items())),
            style="Muted.TLabel", wraplength=960, justify="left").pack(anchor="w", padx=8, pady=6)
        cols = [("at", "bot.col_at", 130, "w"), ("stock", "common.stock", 80, "w"), ("side", "bot.col_side", 70, "w"),
                ("ret", "bot.col_return", 80, "e"), ("money", "bot.col_stake", 110, "e"), ("pnl", "bot.col_profit", 110, "e"),
                ("entry", "bot.col_entry", 80, "e"), ("exit", "bot.col_exit", 80, "e"), ("held", "bot.col_held", 70, "e"),
                ("reason", "bot.col_reason", 170, "w")]
        f, tree = scrolled(win, lambda m: SortableTree(m, cols))
        f.pack(fill="both", expand=True)
        tree.tag_configure("up", foreground=THEME["up"])
        tree.tag_configure("down", foreground=THEME["down"])
        tree.sort_col, tree.sort_desc = "at", True
        rows = []
        for i, r in enumerate(hist["trades"]):
            reason = "bot.reason.target_loss" if r["reason"] == "target" and r["pnl"] < 0 else f"bot.reason.{r['reason']}"
            rows.append((str(i), (fmt.clock(r["time_ms"], with_date=True), r["stock_id"], t(f"side.{r['side']}"), fmt.pct(r["ret"]),
                                  fmt.num(r["money"], 0), fmt.num(r["pnl"], 0), fmt.price(r["entry"]), fmt.price(r["exit"]),
                                  r["held_s"] if r["held_s"] is not None else "–", t(reason)),
                         dict(at=r["time_ms"], stock=r["stock_id"], side=r["side"], ret=r["ret"], money=r["money"],
                              pnl=r["pnl"], entry=r["entry"], exit=r["exit"], held=r["held_s"] or 0, reason=r["reason"]),
                         ("up" if r["pnl"] > 0 else "down" if r["pnl"] < 0 else "",)))
        tree.set_rows(rows)

    def _export_trades(self, parent) -> None:
        path = filedialog.asksaveasfilename(parent=parent, title=t("bot.trades.export_title"), defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")], initialfile="screenstocks-bot-trades.csv")
        if path:
            self._file_action(t("bot.trades.export_title"), lambda: bot.export_trades_csv(bot.load_results(self.app.db), path),
                              t("bot.trades_exported", path=path), parent, path=path)

    def _show_detail(self) -> None:
        """Window with every simulated trade and a per-stock summary."""
        res = self.last_test
        if not res:
            return
        win = tk.Toplevel(self)
        win.title(t("bot.detail.title"))
        win.geometry("900x520")
        win.configure(bg=THEME["panel"])
        ttk.Button(win, text=t("bot.export_results"), command=lambda: self._export_results(win)).pack(
            anchor="e", padx=8, pady=(8, 0))
        per: dict[str, list] = {}
        for x in res["trades"]:
            per.setdefault(x["stock_id"], []).append(x["pnl"])
        ttk.Label(win, text=t("bot.detail.per_stock") + ":  " + "   ".join(
            f"{sid}: {len(v)}× {fmt.num(sum(v), 0)}" for sid, v in sorted(per.items())),
            style="Section.TLabel", wraplength=860, justify="left").pack(anchor="w", padx=8, pady=8)
        total = res["hours"] * 3600
        for w in (900, 3600, 10800, 21600):
            if w < total:
                part = [x for x in res["trades"] if x["exit_s"] >= total - w]
                wins = sum(x["ret"] > 0 for x in part)
                ttk.Label(win, text=t("bot.detail.period", period=f"{w // 60} min" if w < 3600 else f"{w // 3600} h",
                                      n=len(part), win=f"{100 * wins / len(part):.0f}" if part else "–",
                                      profit=fmt.num(sum(x["pnl"] for x in part), 0)),
                          style="Muted.TLabel").pack(anchor="w", padx=8)
        cols = [("n", "#", 40, "e"), ("at", "bot.col_at", 130, "w"), ("stock", "common.stock", 90, "w"),
                ("side", "bot.col_side", 80, "w"), ("ret", "bot.col_return", 90, "e"),
                ("stake", "bot.col_stake", 110, "e"), ("profit", "bot.col_profit", 110, "e"),
                ("reason", "bot.col_reason", 160, "w")]
        f, tree = scrolled(win, lambda m: SortableTree(m, cols))
        f.pack(fill="both", expand=True)
        tree.tag_configure("up", foreground=THEME["up"])
        tree.tag_configure("down", foreground=THEME["down"])
        rows = []
        for i, x in enumerate(res["trades"], 1):
            profit = x["pnl"]
            rows.append((str(i), (i, fmt.clock(res["times_ms"][x["exit_s"]], with_date=True), x["stock_id"], t(f"side.{x['side']}"),
                                  fmt.pct(x["ret"]), fmt.num(x["stake"], 0), fmt.num(profit, 0),
                                  t("bot.reason.target_loss" if x["reason"] == "target" and profit < 0 else f"bot.reason.{x['reason']}")),
                         dict(n=i, at=x["exit_s"], stock=x["stock_id"], side=x["side"], ret=x["ret"],
                              stake=x["stake"], profit=profit, reason=x["reason"]),
                         ("up" if profit > 0 else "down",)))
        tree.set_rows(rows)

    # ---------------------------------------------------------------- refresh

    def _state_sentence(self, s: "bot.BotSettings", held: dict) -> tuple[str, str]:
        eng = self.app.engine
        text, tone = bot.state_sentence(s, eng.state, eng.bot, held)
        return text, {"ok": THEME["up"], "warn": THEME["warn"]}.get(tone, THEME["fg"])

    def refresh(self, ctx: "Ctx") -> None:
        s = bot.load_settings(ctx.db)
        held = bot.BotTrader.held(ctx.db)
        text, color = self._state_sentence(s, held)
        self.state.configure(text=text, foreground=color)
        self._sync_stock_checks(ctx, s)
        self._fill_params(s)

        res = bot.load_results(ctx.db)
        sm = bot.summarize(res["trades"])
        if not sm["n"]:
            self.results.configure(text=t("bot.results.none"))
        else:
            self.results.configure(text=t(
                "bot.results", gain=("+" if sm["gain"] >= 0 else "") + fmt.num(sm["gain"], 0), n=sm["n"], win=f"{sm['win_rate']:.0f}",
                best=f"{sm['best']['sid']} {fmt.pct(sm['best']['ret'])}",
                worst=f"{sm['worst']['sid']} {fmt.pct(sm['worst']['ret'])}"))

        rows = []
        for sid, h in held.items():
            last = ctx.last_prices.get(sid)
            gain = ((last[1] / h["entry_price"] - 1) * (1 if h["side"] == "long" else -1) * 100) if last else None
            rows.append((sid, (sid, t(f"side.{h['side']}"), fmt.price(h["entry_price"]), fmt.price(h.get("target")),
                               fmt.pct(gain)),
                         dict(stock=sid, side=h["side"], entry=h["entry_price"], target=h.get("target"), gain=gain),
                         ("up" if gain and gain > 0 else "down" if gain and gain < 0 else "",)))
        self.pos_tree.set_rows(rows)

        tr = self.app.engine.bot
        age = round(time.time() - tr.last_check_ms / 1000) if tr.last_check_ms else None
        self.think_status.configure(text="● " + (t("bot.think_alive", s=age, n=tr.watching) if age is not None and age <= 10
                                                 else t("bot.think_stale", s="–" if age is None else age)))
        self.think_tree.set_rows([
            (str(i), (fmt.clock(ms, with_date=True), msg), dict(time=ms, msg=msg), ())
            for i, (ms, _sid, msg, _code) in enumerate(self._thoughts())
        ])
        prefix = f"{t('bot.name')}: "
        self.log_tree.set_rows([
            (str(lid), (fmt.clock(ts, with_date=True), msg[len(prefix):]), dict(time=lid, msg=msg), ())
            for lid, ts, rid, sid, msg in ctx.db.rule_log(300) if msg.startswith(prefix)
        ])

