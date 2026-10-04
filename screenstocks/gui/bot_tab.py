"""The Bot tab: mean-reversion trader switch, parameters, live signals and backtest."""

import threading
import tkinter as tk
from dataclasses import asdict
from tkinter import ttk
from typing import TYPE_CHECKING, Optional

from .. import bot
from ..i18n import t
from ..storage import Storage
from . import fmt
from .theme import THEME
from .widgets import SortableTree, scrolled

if TYPE_CHECKING:
    from .app import Ctx

PARAMS = ("entry_z", "exit_z", "tau_s", "min_edge_pct", "stop_pct", "max_hold_s", "trade_pct", "max_positions")
RANGES = (("1h", 3600), ("6h", 6 * 3600), ("24h", 24 * 3600), ("all", None))


class BotTab(ttk.Frame):
    SIGNAL_COLUMNS = [
        ("stock", "common.stock", 80, "w"),
        ("price", "common.price", 90, "e"),
        ("fair", "bot.col_fair", 90, "e"),
        ("z", "bot.col_z", 70, "e"),
        ("edge", "bot.col_edge", 80, "e"),
        ("signal", "bot.col_signal", 160, "w"),
        ("pos", "bot.col_position", 160, "w"),
    ]
    LOG_COLUMNS = [
        ("time", "common.time", 130, "w"),
        ("stock", "common.stock", 75, "w"),
        ("msg", "auto.col_message", 700, "w"),
    ]

    def __init__(self, master, app):
        super().__init__(master, style="Panel.TFrame")
        self.app = app
        s = bot.load_settings(app.db)
        self.vars: dict[str, tk.Variable] = {"enabled": tk.BooleanVar(value=s.enabled),
                                             "shorts": tk.BooleanVar(value=s.shorts)}
        for k in PARAMS:
            self.vars[k] = tk.StringVar(value=f"{getattr(s, k):g}")

        def check(parent, text, var):
            return tk.Checkbutton(parent, text=text, variable=var, command=self._save, bg=THEME["panel_alt"],
                                  fg=THEME["fg"], selectcolor=THEME["panel"], activebackground=THEME["panel_alt"],
                                  activeforeground=THEME["fg"], font=THEME["font_bold"], highlightthickness=0, bd=0)

        card = ttk.Frame(self, style="Card.TFrame", padding=(10, 6))
        card.pack(fill="x", padx=4, pady=(8, 4))
        head = ttk.Frame(card, style="Card.TFrame")
        head.pack(fill="x")
        check(head, t("bot.enable"), self.vars["enabled"]).pack(side="left", padx=(0, 16))
        check(head, t("bot.shorts"), self.vars["shorts"]).pack(side="left", padx=(0, 16))
        self.state = ttk.Label(head, text="", style="CardMuted.TLabel")
        self.state.pack(side="left", padx=8)
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(6, 0))
        for k in PARAMS:
            ttk.Label(row, text=t(f"bot.p.{k}"), style="CardMuted.TLabel").pack(side="left", padx=(8, 3))
            spin = tk.Spinbox(row, from_=0, to=100000, width=5, textvariable=self.vars[k], justify="right",
                              bg=THEME["panel"], fg=THEME["fg"], buttonbackground=THEME["panel_alt"],
                              insertbackground=THEME["fg"], relief="flat", command=self._save)
            spin.pack(side="left")
            spin.bind("<FocusOut>", lambda e: self._save())
            spin.bind("<Return>", lambda e: self._save())
        ttk.Label(card, text=t("bot.help"), style="CardMuted.TLabel", wraplength=1300,
                  justify="left").pack(anchor="w", pady=(6, 0))

        # backtest
        bt = ttk.Frame(self, style="Card.TFrame", padding=(10, 6))
        bt.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Label(bt, text=t("bot.backtest"), style="CardValue.TLabel").pack(side="left", padx=(0, 12))
        self.range_var = tk.StringVar(value="all")
        ttk.Combobox(bt, textvariable=self.range_var, width=5, state="readonly",
                     values=[r[0] for r in RANGES]).pack(side="left", padx=(0, 8))
        self.bt_btn = ttk.Button(bt, text=t("bot.run_backtest"), command=self._run_backtest)
        self.bt_btn.pack(side="left", padx=(0, 12))
        self.bt_result = ttk.Label(bt, text="", style="CardMuted.TLabel", wraplength=1100, justify="left")
        self.bt_result.pack(side="left", fill="x", expand=True)

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, pady=(4, 0))
        sig = ttk.Frame(paned, style="Panel.TFrame")
        ttk.Label(sig, text=t("bot.signals"), style="Section.TLabel").pack(anchor="w", padx=4, pady=(4, 2))
        f, self.signal_tree = scrolled(sig, lambda m: SortableTree(m, self.SIGNAL_COLUMNS, height=8))
        f.pack(fill="both", expand=True)
        self.signal_tree.tag_configure("buy", foreground=THEME["up"])
        self.signal_tree.tag_configure("short", foreground=THEME["down"])
        paned.add(sig, weight=3)
        logf = ttk.Frame(paned, style="Panel.TFrame")
        ttk.Label(logf, text=t("bot.log"), style="Section.TLabel").pack(anchor="w", padx=4, pady=(6, 2))
        f, self.log_tree = scrolled(logf, lambda m: SortableTree(m, self.LOG_COLUMNS, height=6))
        f.pack(fill="both", expand=True)
        self.log_tree.sort_col, self.log_tree.sort_desc = "time", True
        paned.add(logf, weight=2)

    # --------------------------------------------------------------- settings

    def load(self) -> None:
        """Re-read the stored settings into the widgets (after a config import)."""
        s = bot.load_settings(self.app.db)
        self.vars["enabled"].set(s.enabled)
        self.vars["shorts"].set(s.shorts)
        for k in PARAMS:
            self.vars[k].set(f"{getattr(s, k):g}")

    def _save(self) -> None:
        """Store switches and parameters; invalid numbers keep their previous value."""
        old = bot.load_settings(self.app.db)
        values = {"enabled": bool(self.vars["enabled"].get()), "shorts": bool(self.vars["shorts"].get())}
        for k in PARAMS:
            cur = getattr(old, k)
            try:
                v = float(str(self.vars[k].get()).replace(",", "."))
                if v <= 0 and k != "exit_z":
                    raise ValueError
                values[k] = int(v) if isinstance(cur, int) else v
            except ValueError:
                values[k] = cur
                self.vars[k].set(f"{cur:g}")
        new = bot.BotSettings(**values)
        if new != old:
            bot.save_settings(self.app.db, new)

    # --------------------------------------------------------------- backtest

    def _run_backtest(self) -> None:
        self._save()
        s = bot.load_settings(self.app.db)
        seconds = dict(RANGES)[self.range_var.get()]
        self.bt_btn.state(["disabled"])
        self.bt_result.configure(text=t("bot.running"))
        path = self.app.db.path
        snap = self.app.db.latest_snapshot() or {}
        cds = (snap.get("buy_cooldown_s") or 85, snap.get("short_cooldown_s") or 85)

        def work():
            db = Storage(path)
            try:
                end = db.latest_time_ms() or 0
                start = db.first_time_ms() or 0
                if seconds:
                    start = max(start, end - seconds * 1000)
                res = bot.backtest(db, s, start, end, buy_cd_s=cds[0], short_cd_s=cds[1])
                text = t("bot.result", n=res["n"], win=f"{res['win_rate']:.0f}", avg=fmt.num(res["avg_ret"], 2),
                         median=fmt.num(res["median_ret"], 2), dd=f"{res['max_dd']:.0f}", hours=f"{res['hours']:.1f}",
                         target=res["reasons"]["target"], stop=res["reasons"]["stop"],
                         timeout=res["reasons"]["timeout"])
                text += "\n" + "   ".join(f"{k}: {n}× {fmt.num(v, 1)}%" for k, (n, v) in sorted(res["per_stock"].items()))
            except Exception as exc:
                text = t("common.error", error=exc)
            finally:
                db.close()
            self.after(0, lambda: (self.bt_result.configure(text=text), self.bt_btn.state(["!disabled"])))

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- refresh

    def refresh(self, ctx: "Ctx") -> None:
        engine = self.app.engine
        s = bot.load_settings(ctx.db)
        on = s.enabled and engine.state == "active"
        self.state.configure(text=t("bot.state_on") if on else t("bot.state_off"),
                             foreground=THEME["up"] if on else THEME["warn"])
        strat = engine.bot.strategy
        held = engine.bot._held(ctx.db)
        rows = []
        for st in ctx.stocks:
            sid = st["stock_id"]
            last = ctx.last_prices.get(sid)
            price = last[1] if last else None
            z = engine.bot.last_z.get(sid)
            fair = strat.fair.get(sid) if strat else None
            edge = (fair / price - 1) * 100 if fair and price else None
            signal, tag = "", ()
            if z is None:
                signal = t("bot.warming")
            elif z <= -s.entry_z and edge is not None and edge >= s.min_edge_pct:
                signal, tag = t("bot.sig_buy"), ("buy",)
            elif s.shorts and z >= s.entry_z and edge is not None and -edge >= s.min_edge_pct:
                signal, tag = t("bot.sig_short"), ("short",)
            h = held.get(sid)
            pos = ""
            if h:
                side = t(f"side.{h['side']}")
                pnl = ((price / h["entry_price"] - 1) * (1 if h["side"] == "long" else -1) * 100
                       if price else None)
                pos = f"{side} {fmt.price(h['entry_price'])} ({fmt.pct(pnl)})"
            rows.append((sid, (sid, fmt.price(price), fmt.price(fair), "–" if z is None else f"{z:+.2f}",
                               fmt.pct(edge), signal, pos),
                         dict(stock=sid, price=price, fair=fair, z=z, edge=edge, signal=signal, pos=pos), tag))
        self.signal_tree.set_rows(rows)
        prefix = f"{t('bot.name')} "
        self.log_tree.set_rows([
            (str(lid), (fmt.clock(ts, with_date=True), sid, msg), dict(time=lid, stock=sid, msg=msg), ())
            for lid, ts, rid, sid, msg in ctx.db.rule_log(300) if msg.startswith(prefix)
        ])
