"""tkinter dashboard on top of the recorded history."""

import time
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import threading
import webbrowser

from .. import __version__, config, settings as settings_mod, updater
from ..automation import (EXIT_KINDS, KIND_KEYS, MODE_KEYS, SIDE_KEYS, AutomationEngine, condition_met,
                          describe_trigger, has_position, kind_name, mode_name, needs_position, side_name,
                          trigger_price)
from ..collector import Collector, CollectorStatus
from ..commands import ACTIONS, CommandWriter, action_label, action_name, normalize_percent, reason_text, status_text
from ..i18n import t
from ..storage import Storage
from . import fmt
from .chart import HLine, LineChart, Marker, Series, blend
from .analysis import DividendTab, JournalTab, StatsTab
from .theme import THEME, apply_style, set_window_icon
from .widgets import RangeBar, SortableTree, scrolled


# trade kind -> chart colour (letter and label come from i18n: tradekind.*)
TRADE_COLORS = {"buy": "#3fb950", "sell": "#f85149", "short": "#a371f7", "cover": "#58a6ff"}
RULE_COLORS = {
    "stop_loss": "#f85149",
    "take_profit": "#3fb950",
    "trailing_stop": "#f0883e",
    "buy_limit": "#56d4dd",
    "short_limit": "#d2a8ff",
}


@dataclass
class Ctx:
    """Everything a tab needs for one refresh."""
    db: Storage
    status: CollectorStatus
    snap: Optional[dict]
    end_ms: Optional[int]            # newest recorded price time (server clock)
    server_now_ms: Optional[int]     # estimated current server time
    live: bool
    stocks: list[dict] = field(default_factory=list)
    positions: dict = field(default_factory=dict)
    colors: dict = field(default_factory=dict)
    last_prices: dict = field(default_factory=dict)
    div_factor: Optional[float] = None   # detected dividend multiplier (None until the first payout)
    div_count: int = 0

    def dividend_per_min(self, sid: str) -> Optional[float]:
        """Expected payout per minute for the long position in sid."""
        owned = (self.positions.get(sid) or {}).get("shares_owned") or 0.0
        st = next((s for s in self.stocks if s["stock_id"] == sid), None)
        last = self.last_prices.get(sid)
        if not owned or not st or not last or not st.get("dividend_rate"):
            return None
        return owned * last[1] * st["dividend_rate"] * (self.div_factor or 1.0)

    def window(self, seconds: Optional[int]) -> Optional[tuple[int, int]]:
        if self.end_ms is None:
            return None
        # Never reach back further than the recorded history, so the chart fills the width.
        first = self.db.first_time_ms() or self.end_ms
        start = first if seconds is None else max(first, self.end_ms - seconds * 1000)
        return start, self.end_ms


def stock_label(st: dict) -> str:
    name = st.get("name")
    return st["stock_id"] if not name or name == st["stock_id"] else f"{st['stock_id']} ({name})"


# ---------------------------------------------------------------------- trading

class TradePanel(ttk.Frame):
    """Buy / sell / short / cover / close the selected stock by percentage."""

    BUTTONS = [  # (action, colour, row, column, columnspan)
        ("buy", THEME["up"], 0, 0, 1),
        ("sell", THEME["down"], 0, 1, 1),
        ("short", "#a371f7", 1, 0, 1),
        ("cover", THEME["accent"], 1, 1, 1),
        ("close", "#6e7681", 2, 0, 2),
    ]
    RESULT_COLUMNS = [
        ("time", "common.time", 62, "w"),
        ("stock", "common.stock", 62, "w"),
        ("action", "trade.col_action", 78, "w"),
        ("pct", "%", 36, "e"),
        ("status", "common.status", 120, "w"),
    ]
    TIMEOUT_S = 8.0

    def __init__(self, master, app: "App"):
        super().__init__(master, style="Card.TFrame", padding=(10, 8), width=340)
        self.app = app
        self.stock_id: Optional[str] = None
        self._ctx: Optional[Ctx] = None
        self._pending = None  # (SentCommand, known result ids, local send time)
        self.pct_var = tk.StringVar(value="25")
        self.confirm_var = tk.BooleanVar(value=True)

        self.title = ttk.Label(self, text=t("trade.title"), style="CardTitle.TLabel")
        self.title.pack(anchor="w")

        grid = ttk.Frame(self, style="Card.TFrame")
        grid.pack(fill="x", pady=(4, 6))
        self.facts: dict[str, ttk.Label] = {}
        for i, (key, title) in enumerate((("price", t("common.price")), ("cash", t("common.cash")),
                                          ("owned", t("common.owned")), ("short", t("common.short")),
                                          ("buy_cd", t("trade.buy_cd")), ("short_cd", t("trade.short_cd")))):
            ttk.Label(grid, text=title, style="CardMuted.TLabel").grid(row=i // 2, column=(i % 2) * 2,
                                                                        sticky="w", padx=(0, 6))
            self.facts[key] = ttk.Label(grid, text="–", style="CardValue.TLabel")
            self.facts[key].grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 14))

        prow = ttk.Frame(self, style="Card.TFrame")
        prow.pack(fill="x", pady=(2, 2))
        ttk.Label(prow, text=t("trade.amount"), style="CardMuted.TLabel").pack(side="left")
        spin = tk.Spinbox(prow, from_=1, to=100, increment=1, width=5, textvariable=self.pct_var,
                          justify="right", font=THEME["font_bold"], bg=THEME["panel"], fg=THEME["fg"],
                          buttonbackground=THEME["panel_alt"], insertbackground=THEME["fg"],
                          relief="flat", command=self._on_pct_changed)
        spin.pack(side="left", padx=(6, 2))
        spin.bind("<KeyRelease>", lambda e: self._on_pct_changed())
        spin.bind("<MouseWheel>", self._on_wheel)
        ttk.Label(prow, text="%", style="CardValue.TLabel").pack(side="left")
        for v in (100, 75, 50, 25, 10):
            tk.Button(prow, text=str(v), width=3, command=lambda v=v: self._set_pct(v), relief="flat",
                      bg=THEME["panel"], fg=THEME["fg"], activebackground=THEME["grid_strong"],
                      activeforeground=THEME["fg"], font=THEME["font_small"], bd=0
                      ).pack(side="right", padx=1)
        self.scale = tk.Scale(self, from_=1, to=100, orient="horizontal", showvalue=False,
                              command=lambda v: self._set_pct(int(float(v)), from_scale=True),
                              bg=THEME["accent"], troughcolor=THEME["panel"], highlightthickness=0,
                              activebackground=blend(THEME["accent"], "#ffffff", 0.8), sliderrelief="flat",
                              sliderlength=18, width=12, bd=0)
        self.scale.set(25)
        self.scale.pack(fill="x", pady=(0, 6))

        btns = ttk.Frame(self, style="Card.TFrame")
        btns.pack(fill="x")
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        self.buttons: dict[str, tk.Button] = {}
        for action, color, r, c, span in self.BUTTONS:
            b = tk.Button(btns, text=action_name(action), command=lambda a=action: self._execute(a),
                          bg=color, fg="#0d1117", activebackground=blend(color, "#ffffff", 0.8),
                          activeforeground="#0d1117", disabledforeground=THEME["muted"],
                          font=THEME["font_bold"], relief="flat", bd=0, pady=5, cursor="hand2")
            b.grid(row=r, column=c, columnspan=span, sticky="ew", padx=2, pady=2)
            b.color = color
            self.buttons[action] = b

        self.preview = ttk.Label(self, text="", style="CardMuted.TLabel", justify="left", wraplength=320)
        self.preview.pack(fill="x", pady=(6, 2))
        tk.Checkbutton(self, text=t("trade.confirm_cb"), variable=self.confirm_var,
                       bg=THEME["panel_alt"], fg=THEME["muted"], selectcolor=THEME["panel"],
                       activebackground=THEME["panel_alt"], activeforeground=THEME["fg"],
                       font=THEME["font_small"], highlightthickness=0, bd=0).pack(anchor="w")
        self.status = ttk.Label(self, text="", style="CardValue.TLabel", wraplength=320, justify="left")
        self.status.pack(fill="x", pady=(4, 6))

        ttk.Label(self, text=t("trade.log"), style="CardMuted.TLabel").pack(anchor="w")
        f, self.results = scrolled(self, lambda m: SortableTree(m, self.RESULT_COLUMNS, height=7))
        f.pack(fill="both", expand=True)
        for tag, color in (("done", THEME["up"]), ("rejected", THEME["down"]),
                           ("failed", THEME["down"]), ("running", THEME["warn"])):
            self.results.tag_configure(tag, foreground=color)
        self.results.sort_col, self.results.sort_desc = "time", True
        self.pack_propagate(False)

    # ------------------------------------------------------------- percentage

    def _percent(self) -> Optional[int]:
        try:
            value = float(self.pct_var.get().replace(",", "."))
        except ValueError:
            return None
        return normalize_percent(value) if value > 0 else None

    def _set_pct(self, v: int, from_scale: bool = False) -> None:
        self.pct_var.set(str(v))
        if not from_scale:
            self.scale.set(v)
        self._update_preview()

    def _on_pct_changed(self) -> None:
        p = self._percent()
        if p is not None:
            self.scale.set(p)
        self._update_preview()

    def _on_wheel(self, e) -> None:
        p = self._percent() or 25
        self._set_pct(normalize_percent(p + (1 if e.delta > 0 else -1)))

    # ---------------------------------------------------------------- refresh

    def _position(self) -> tuple[float, float, float, float]:
        pos = self._ctx.positions.get(self.stock_id, {}) if self._ctx else {}
        return (pos.get("shares_owned", 0.0), pos.get("avg_buy_price", 0.0),
                pos.get("shares_shorted", 0.0), pos.get("avg_short_price", 0.0))

    def _price(self) -> Optional[float]:
        last = self._ctx.last_prices.get(self.stock_id) if self._ctx and self.stock_id else None
        return last[1] if last else None

    def refresh(self, ctx: Ctx, stock_id: Optional[str]) -> None:
        self._ctx, self.stock_id = ctx, stock_id
        self.title.configure(text=t("trade.title_stock", stock=stock_id) if stock_id else t("trade.title"))
        price = self._price()
        owned, avg, shorted, avg_s = self._position()
        snap = ctx.snap or {}
        self.facts["price"].configure(text=fmt.price(price))
        self.facts["cash"].configure(text=fmt.big(snap.get("cash")))
        self.facts["owned"].configure(text=fmt.big(owned) if owned else "0")
        self.facts["short"].configure(text=fmt.big(shorted) if shorted else "0")
        for key, col in (("buy_cd", "next_buy_ms"), ("short_cd", "next_short_ms")):
            nxt = snap.get(col)
            if nxt and ctx.server_now_ms:
                rem = (nxt - ctx.server_now_ms) / 1000
                self.facts[key].configure(text=t("common.ready") if rem <= 0 else fmt.duration(rem),
                                          foreground=THEME["up"] if rem <= 0 else THEME["warn"])
        can_trade = ctx.live and stock_id is not None
        for action, b in self.buttons.items():
            enabled = can_trade and (action not in ("sell",) or owned) and \
                (action not in ("cover",) or shorted) and (action != "close" or owned or shorted)
            b.configure(state="normal" if enabled else "disabled",
                        bg=b.color if enabled else THEME["panel"], cursor="hand2" if enabled else "")
        self._update_preview()
        self._check_pending()
        self._refresh_results()

    def _update_preview(self) -> None:
        p = self._percent()
        if p is None or not self._ctx:
            self.preview.configure(text=t("trade.enter_pct"))
            return
        price = self._price()
        owned, _avg, shorted, _avg_s = self._position()
        cash = (self._ctx.snap or {}).get("cash")
        f = p / 100
        lines = []
        if owned:
            lines.append(t("trade.preview_sell", p=p, shares=fmt.big(owned * f))
                         + (f" ≈ {fmt.big(owned * f * price)}" if price else ""))
        if shorted:
            lines.append(t("trade.preview_cover", p=p, shares=fmt.big(shorted * f))
                         + (f" ≈ {fmt.big(shorted * f * price)}" if price else ""))
        if cash:
            lines.append(t("trade.preview_open", p=p, cash=fmt.big(cash * f)))
        if not self._ctx.live:
            lines.append(t("trade.not_live"))
        self.preview.configure(text="\n".join(lines))

    # -------------------------------------------------------------- execution

    def _set_status(self, text: str, color: str = None) -> None:
        self.status.configure(text=text, foreground=color or THEME["fg"])

    def _execute(self, action: str) -> None:
        ctx, sid = self._ctx, self.stock_id
        label = action_name(action)
        p = self._percent()
        if not ctx or not sid:
            return
        if p is None:
            self._set_status(t("trade.invalid_pct"), THEME["down"])
            return
        if not ctx.live:
            self._set_status(t("trade.not_live_short"), THEME["down"])
            return
        if self._pending:
            self._set_status(t("trade.busy"), THEME["warn"])
            return
        writer = self.app.commands
        if writer.commands_enabled() is False:
            self._set_status(t("trade.commands_disabled"), THEME["down"])
            return
        if self.confirm_var.get() and not messagebox.askyesno(
                t("trade.confirm_title"), t("trade.confirm_text", action=label, p=p, stock=sid,
                                            preview=self.preview.cget("text")),
                parent=self):
            return
        known = {r["id"] for r in ctx.db.command_results(200)}
        try:
            sent = writer.send(sid, action, p)
        except Exception as exc:
            self._set_status(t("common.error", error=exc), THEME["down"])
            return
        self._pending = (sent, known, time.time())
        self._set_status(t("trade.sent", action=label, p=p, stock=sid), THEME["warn"])
        self.after(700, self.app.refresh_now)

    def _check_pending(self) -> None:
        if not self._pending or not self._ctx:
            return
        sent, known, t_sent = self._pending
        label = action_name(sent.action)
        prefix = ACTIONS[sent.action]
        new = [r for r in self._ctx.db.command_results(50)
               if r["id"] not in known and r["stock_id"] == sent.stock_id and (r["action"] or "").startswith(prefix)]
        if new:
            r = new[0]
            status = r["status"]
            reason = reason_text(r["reason"])
            text = t("trade.result", action=label, p=sent.percent, stock=sent.stock_id, status=status_text(status))
            if reason:
                text += f" – {reason}"
            if status == "done":
                self._set_status("✔ " + text, THEME["up"])
            elif status in ("rejected", "failed"):
                self._set_status("✖ " + text, THEME["down"])
            else:
                self._set_status("… " + text, THEME["warn"])
                return
            self._pending = None
            return
        if time.time() - t_sent > self.TIMEOUT_S:
            disarmed = self.app.commands.cancel(sent)
            self._pending = None
            self._set_status(
                t("trade.not_picked_up") if disarmed else t("trade.no_response"), THEME["down"])

    def _refresh_results(self) -> None:
        rows = []
        for r in self._ctx.db.command_results(100):
            status = status_text(r["status"])
            reason = reason_text(r["reason"])
            ts = r["finished_ms"] or r["received_ms"]
            rows.append((r["id"], (fmt.clock(ts), r["stock_id"], action_label(r["action"]),
                                   f"{r['percent']:g}" if r["percent"] else "",
                                   f"{status}: {reason}" if reason else status),
                         dict(time=ts, stock=r["stock_id"], action=r["action"], pct=r["percent"], status=status),
                         (r["status"],)))
        self.results.set_rows(rows)


# ------------------------------------------------------------------------ tabs

class MarketTab(ttk.Frame):
    COLUMNS = [
        ("ticker", "col.ticker", 80, "w"),
        ("name", "col.name", 70, "w"),
        ("price", "common.price", 90, "e"),
        ("d1", "Δ 1m", 75, "e"),
        ("d5", "Δ 5m", 75, "e"),
        ("d15", "Δ 15m", 75, "e"),
        ("d60", "Δ 1h", 75, "e"),
        ("base", "col.base", 65, "e"),
        ("cap", "col.cap", 70, "e"),
        ("div", "col.dividend", 75, "e"),
        ("avail", "col.available", 90, "e"),
        ("maxvol", "col.max_volume", 75, "e"),
        ("owned", "common.owned", 90, "e"),
        ("avg", "common.avg_buy", 80, "e"),
        ("short", "common.short", 80, "e"),
        ("pl", "common.pl", 95, "e"),
        ("div_min", "col.div_min", 90, "e"),
    ]

    def __init__(self, master, app: "App"):
        super().__init__(master, style="Panel.TFrame")
        self.app = app
        self.selected: Optional[str] = None

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True)

        top = ttk.Frame(paned, style="Panel.TFrame")
        table_frame, self.tree = scrolled(top, lambda f: SortableTree(f, self.COLUMNS, height=9,
                                                                      selectmode="browse"))
        table_frame.pack(fill="both", expand=True)
        self.tree.tag_configure("up", foreground=THEME["up"])
        self.tree.tag_configure("down", foreground=THEME["down"])
        self.tree.tag_configure("locked", foreground=THEME["muted"])
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        paned.add(top, weight=1)

        bottom = ttk.Frame(paned, style="Panel.TFrame")
        bar = ttk.Frame(bottom, style="Panel.TFrame")
        bar.pack(fill="x", pady=(6, 4))
        self.title = ttk.Label(bar, text="", style="Title.TLabel")
        self.title.pack(side="left", padx=(4, 16))
        self.range = RangeBar(bar, self.refresh_chart)
        self.range.pack(side="left")
        ttk.Button(bar, text=t("market.export_csv"), command=self._export).pack(side="right", padx=4)

        body = ttk.Frame(bottom, style="Panel.TFrame")
        body.pack(fill="both", expand=True)
        self.trade = TradePanel(body, app)
        self.trade.pack(side="right", fill="y", padx=(8, 0))
        left = ttk.Frame(body, style="Panel.TFrame")
        left.pack(side="left", fill="both", expand=True)
        self.chart = LineChart(left, THEME, y_fmt=fmt.price, height=320)
        self.chart.pack(fill="both", expand=True)
        self.info = ttk.Label(left, text="", style="Muted.TLabel")
        self.info.pack(fill="x", padx=4, pady=(4, 2))
        paned.add(bottom, weight=3)

        self._ctx: Optional[Ctx] = None

    def _on_select(self, _e=None) -> None:
        sel = self.tree.selection()
        if sel:
            self.selected = sel[0]
            self.refresh_chart()
            if self._ctx:
                self.trade.refresh(self._ctx, self.selected)

    def refresh(self, ctx: Ctx) -> None:
        self._ctx = ctx
        db = ctx.db
        rows = []
        for st in ctx.stocks:
            sid = st["stock_id"]
            last = ctx.last_prices.get(sid)
            price = last[1] if last else st.get("last_price")
            t_ref = last[0] if last else ctx.end_ms
            deltas = {}
            for key, secs in (("d1", 60), ("d5", 300), ("d15", 900), ("d60", 3600)):
                old = db.price_at(sid, t_ref - secs * 1000) if t_ref else None
                deltas[key] = fmt.change_pct(price, old)
            pos = ctx.positions.get(sid, {})
            owned, avg = pos.get("shares_owned", 0.0), pos.get("avg_buy_price", 0.0)
            shorted, avg_short = pos.get("shares_shorted", 0.0), pos.get("avg_short_price", 0.0)
            pl = None
            if price is not None and (owned or shorted):
                pl = (price - avg) * owned + (avg_short - price) * shorted

            div = ctx.dividend_per_min(sid)
            d5 = deltas["d5"]
            tags = ("locked",) if not st.get("unlocked", 1) else \
                ("up",) if d5 and d5 > 0 else ("down",) if d5 and d5 < 0 else ()
            values = (
                sid, st.get("name") or "", fmt.price(price),
                fmt.pct(deltas["d1"]), fmt.pct(deltas["d5"]), fmt.pct(deltas["d15"]), fmt.pct(deltas["d60"]),
                fmt.price(st.get("base_price")), fmt.price(st.get("price_cap")),
                fmt.pct((st.get("dividend_rate") or 0) * 100, signed=False),
                fmt.big(st.get("available_shares")), fmt.num(st.get("max_volume"), 0),
                fmt.big(owned) if owned else "", fmt.price(avg) if owned else "",
                fmt.big(shorted) if shorted else "", fmt.big(pl) if pl is not None else "",
                fmt.big(div) if div else "",
            )
            sort_values = dict(ticker=sid, name=st.get("name"), price=price, **deltas,
                               base=st.get("base_price"), cap=st.get("price_cap"), div=st.get("dividend_rate"),
                               avail=st.get("available_shares"), maxvol=st.get("max_volume"),
                               owned=owned or None, avg=avg or None, short=shorted or None, pl=pl,
                               div_min=div)
            rows.append((sid, values, sort_values, tags))
        self.tree.set_rows(rows)

        if (self.selected is None or not self.tree.exists(self.selected)) and rows:
            self.selected = rows[0][0]
            self.tree.selection_set(self.selected)
        self.refresh_chart()
        self.trade.refresh(ctx, self.selected)

    def refresh_chart(self) -> None:
        ctx = self._ctx
        if not ctx or not self.selected:
            self.chart.set_data([], empty_text=t("common.no_data"))
            return
        sid = self.selected
        st = next((s for s in ctx.stocks if s["stock_id"] == sid), {"stock_id": sid})
        self.title.configure(text=stock_label(st))
        win = ctx.window(self.range.seconds)
        if not win:
            self.chart.set_data([], empty_text=t("common.no_data"))
            return
        since, until = win
        db = ctx.db
        pts = db.price_series(sid, since, until, max_points=max(200, self.chart.winfo_width()))
        color = ctx.colors.get(sid, THEME["accent"])

        news = [
            Marker(ts, p, THEME["up"] if kind == "high" else THEME["down"], kind == "high",
                   t("market.news_marker", kind=t("news.high_word") if kind == "high" else t("news.low_word"),
                     lookback=f"{lb:g}", price=fmt.price(p)))
            for ts, _sid, p, kind, lb in db.news(sid, since_ms=since)
        ]
        trades = db.trades(sid, since, until)
        markers = news + [
            Marker(tr["time_ms"], tr["price"], TRADE_COLORS[tr["kind"]], True,
                   t("market.trade_marker", kind=t(f"tradekind.{tr['kind']}"), shares=fmt.big(tr["shares"]),
                     price=fmt.price(tr["price"])),
                   letter=t(f"tradekind.{tr['kind']}.letter"))
            for tr in trades if tr["price"]
        ]
        hlines = []
        pos = ctx.positions.get(sid)
        for rule in db.rules(enabled_only=True):
            if rule["stock_id"] == sid:
                trig = trigger_price(rule, pos)
                if trig:
                    hlines.append(HLine(trig, RULE_COLORS[rule["kind"]],
                                        f"{kind_name(rule['kind'])} #{rule['id']}"))
        if pos and pos["shares_owned"]:
            hlines.append(HLine(pos["avg_buy_price"], THEME["accent"], t("common.avg_buy")))
        if pos and pos["shares_shorted"]:
            hlines.append(HLine(pos["avg_short_price"], "#d2a8ff", t("common.avg_short")))

        upcoming = []
        now = ctx.server_now_ms or until
        for s_sid, direction, target, sched_ms, _pub in db.scheduled(50):
            if s_sid == sid and sched_ms >= now:
                hlines.append(HLine(target, THEME["warn"], t("market.scheduled_line", direction=direction)))
                upcoming.append(t("market.scheduled_info", direction=direction, target=fmt.price(target),
                                  time=fmt.clock(sched_ms), countdown=fmt.duration((sched_ms - now) / 1000)))

        self.chart.set_data([Series(sid, color, pts)], markers, hlines, x_range=(since, until),
                            empty_text=t("market.no_prices"))

        parts = []
        stats = db.range_stats(sid, since, until)
        if stats and pts:
            lo, hi, avg, n = stats
            first = db.price_at(sid, since) or pts[0][1]
            last = pts[-1][1]
            parts.append(t("market.stats", range=self.range.label, lo=fmt.price(lo), hi=fmt.price(hi),
                           avg=fmt.price(avg), change=fmt.pct(fmt.change_pct(last, first)),
                           spread=fmt.pct((hi / lo - 1) * 100 if lo else None, signed=False), n=fmt.num(n, 0)))
        if news:
            parts.append(t("market.news_count", n=len(news)))
        if trades:
            parts.append(t("market.trade_count", n=len(trades)))
        parts += upcoming
        self.info.configure(text="     ".join(parts))

    def _export(self) -> None:
        ctx = self._ctx
        win = ctx.window(self.range.seconds) if ctx else None
        if not win:
            messagebox.showinfo("Export", t("export.none"))
            return
        path = filedialog.asksaveasfilename(
            title=t("export.title"), defaultextension=".csv",
            initialfile=f"screenstocks_{self.range.var.get().replace('common.all', 'all')}_{datetime.now():%Y%m%d_%H%M%S}.csv",
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        n = ctx.db.export_prices_csv(Path(path), *win)
        messagebox.showinfo("Export", t("export.done", n=fmt.num(n, 0), path=path))


class CompareTab(ttk.Frame):
    """All stocks on one chart, normalised to % change since range start."""

    def __init__(self, master, app: "App"):
        super().__init__(master, style="Panel.TFrame")
        self.app = app
        bar = ttk.Frame(self, style="Panel.TFrame")
        bar.pack(fill="x", pady=(6, 4))
        self.range = RangeBar(bar, self._rerender)
        self.range.pack(side="left", padx=4)
        self.checks_frame = ttk.Frame(self, style="Panel.TFrame")
        self.checks_frame.pack(fill="x", padx=4)
        self.vars: dict[str, tk.BooleanVar] = {}
        self.chart = LineChart(self, THEME, y_fmt=lambda v: fmt.pct(v))
        self.chart.pack(fill="both", expand=True, pady=(4, 0))
        self._ctx: Optional[Ctx] = None

    def _rerender(self) -> None:
        if self._ctx:
            self.refresh(self._ctx)

    def refresh(self, ctx: Ctx) -> None:
        self._ctx = ctx
        ids = [s["stock_id"] for s in ctx.stocks]
        key = [(sid, ctx.colors.get(sid)) for sid in ids]
        if getattr(self, "_check_key", None) != key:
            self._check_key = key
            for w in self.checks_frame.winfo_children():
                w.destroy()
            self.vars = {sid: self.vars.get(sid, tk.BooleanVar(value=True)) for sid in ids}
            for sid in ids:
                tk.Checkbutton(self.checks_frame, text=sid, variable=self.vars[sid], command=self._rerender,
                               bg=THEME["panel"], fg=ctx.colors.get(sid, THEME["fg"]),
                               selectcolor=THEME["panel_alt"], activebackground=THEME["panel"],
                               activeforeground=THEME["fg"], font=THEME["font_bold"],
                               highlightthickness=0, bd=0).pack(side="left", padx=(0, 10))

        win = ctx.window(self.range.seconds)
        series = []
        if win:
            for sid in ids:
                if not self.vars[sid].get():
                    continue
                pts = ctx.db.price_series(sid, *win, max_points=max(200, self.chart.winfo_width() // 2))
                if not pts:
                    continue
                base = ctx.db.price_at(sid, win[0]) or pts[0][1]
                if not base:
                    continue
                norm = [(ts, (v / base - 1) * 100, (lo / base - 1) * 100, (hi / base - 1) * 100)
                        for ts, v, lo, hi in pts]
                series.append(Series(sid, ctx.colors.get(sid, THEME["accent"]), norm, width=2))
        self.chart.set_data(series, hlines=[HLine(0.0, THEME["muted"], "", fit=True)] if series else [],
                            x_range=win, empty_text=t("common.no_data"))


class PortfolioTab(ttk.Frame):
    POS_COLUMNS = [
        ("stock", "common.stock", 80, "w"),
        ("owned", "common.owned", 95, "e"),
        ("avg", "common.avg_buy", 85, "e"),
        ("price", "common.price", 85, "e"),
        ("value", "pf.value", 100, "e"),
        ("pl", "common.pl", 100, "e"),
        ("plp", "pf.pl_pct", 80, "e"),
        ("short", "common.short", 95, "e"),
        ("avg_short", "common.avg_short", 85, "e"),
        ("short_pl", "pf.short_pl", 100, "e"),
        ("div_min", "col.div_min", 90, "e"),
    ]
    DIV_COLUMNS = [
        ("time", "common.time", 140, "w"),
        ("amount", "pf.div_amount", 120, "e"),
        ("factor", "pf.div_factor_col", 80, "e"),
    ]
    CHANGE_COLUMNS = [
        ("time", "common.time", 120, "w"),
        ("stock", "common.stock", 70, "w"),
        ("owned", "common.owned", 95, "e"),
        ("avg", "common.avg_buy", 80, "e"),
        ("short", "common.short", 95, "e"),
        ("avg_short", "common.avg_short", 80, "e"),
    ]

    def __init__(self, master, app: "App"):
        super().__init__(master, style="Panel.TFrame")
        self.app = app
        kpis = ttk.Frame(self, style="Panel.TFrame")
        kpis.pack(fill="x", pady=(8, 4))
        self.kpi: dict[str, ttk.Label] = {}
        for key, title in (("net", t("common.net_worth")), ("cash", t("common.cash")), ("invested", t("pf.invested")),
                           ("delta", t("pf.delta")), ("pl", t("pf.open_pl")), ("div_min", t("pf.div_min")),
                           ("div_sum", t("pf.div_received"))):
            box = ttk.Frame(kpis, style="Card.TFrame", padding=(12, 6))
            box.pack(side="left", padx=4, fill="y")
            ttk.Label(box, text=title, style="CardMuted.TLabel").pack(anchor="w")
            self.kpi[key] = ttk.Label(box, text="–", style="Kpi.TLabel")
            self.kpi[key].pack(anchor="w")
            if key == "div_min":
                self.div_caption = ttk.Label(box, text="", style="CardMuted.TLabel")
                self.div_caption.pack(anchor="w")

        bar = ttk.Frame(self, style="Panel.TFrame")
        bar.pack(fill="x", pady=4)
        self.range = RangeBar(bar, self._rerender, default="1h")
        self.range.pack(side="left", padx=4)

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True)
        self.chart = LineChart(paned, THEME, y_fmt=fmt.big, height=260)
        paned.add(self.chart, weight=3)

        lower = ttk.Frame(paned, style="Panel.TFrame")
        lpan = ttk.PanedWindow(lower, orient="horizontal")
        lpan.pack(fill="both", expand=True)
        # left: open positions above the dividend payouts; right: position changes
        left = ttk.PanedWindow(lpan, orient="vertical")
        posf = ttk.Frame(left, style="Panel.TFrame")
        ttk.Label(posf, text=t("pf.positions"), style="Section.TLabel").pack(anchor="w", pady=(4, 2))
        f, self.pos_tree = scrolled(posf, lambda m: SortableTree(m, self.POS_COLUMNS, height=4))
        f.pack(fill="both", expand=True)
        left.add(posf, weight=1)
        right = ttk.Frame(lpan, style="Panel.TFrame")
        ttk.Label(right, text=t("pf.changes"), style="Section.TLabel").pack(anchor="w", pady=(4, 2))
        f, self.chg_tree = scrolled(right, lambda m: SortableTree(m, self.CHANGE_COLUMNS, height=6))
        f.pack(fill="both", expand=True)
        divf = ttk.Frame(left, style="Panel.TFrame")
        ttk.Label(divf, text=t("pf.dividends"), style="Section.TLabel").pack(anchor="w", pady=(4, 2))
        f, self.div_tree = scrolled(divf, lambda m: SortableTree(m, self.DIV_COLUMNS, height=6))
        f.pack(fill="both", expand=True)
        self.div_tree.sort_col, self.div_tree.sort_desc = "time", True
        for tree in (self.pos_tree, self.chg_tree, self.div_tree):
            tree.tag_configure("up", foreground=THEME["up"])
            tree.tag_configure("down", foreground=THEME["down"])
        left.add(divf, weight=1)
        lpan.add(left, weight=3)
        lpan.add(right, weight=2)
        paned.add(lower, weight=2)
        self._ctx: Optional[Ctx] = None

    def _rerender(self) -> None:
        if self._ctx:
            self.refresh(self._ctx)

    def refresh(self, ctx: Ctx) -> None:
        self._ctx = ctx
        db, snap = ctx.db, ctx.snap
        net = snap.get("net_worth") if snap else None
        cash = snap.get("cash") if snap else None
        self.kpi["net"].configure(text=fmt.big(net))
        self.kpi["cash"].configure(text=fmt.big(cash))
        self.kpi["invested"].configure(text=fmt.big(net - cash) if net is not None and cash is not None else "–")

        # portfolio chart uses snapshot (server) time
        until = snap["server_ms"] if snap else None
        win = None
        if until:
            secs = self.range.seconds
            first = db.conn.execute("SELECT MIN(server_ms) FROM snapshots").fetchone()[0] or until
            win = (first if secs is None else max(first, until - secs * 1000), until)
        if win:
            rows = db.portfolio_series(*win, max_points=max(200, self.chart.winfo_width()))
            series = [Series(t("common.net_worth"), THEME["accent"], [(ts, n, n, n) for ts, n, _c in rows]),
                      Series(t("common.cash"), THEME["up"], [(ts, c, c, c) for ts, _n, c in rows])]
            self.chart.set_data(series, x_range=win, empty_text=t("pf.no_data"))
            received = db.dividend_sum(*win)
            self.kpi["div_sum"].configure(text=fmt.big(received) if received else "–",
                                          style="KpiUp.TLabel" if received else "Kpi.TLabel")
            start_net = db.snapshot_value_at("net_worth", win[0]) or (rows[0][1] if rows else None)
            delta = net - start_net if net is not None and start_net is not None else None
            self.kpi["delta"].configure(
                text=f"{fmt.big(delta)}  ({fmt.pct(fmt.change_pct(net, start_net))})" if delta is not None else "–",
                style="KpiUp.TLabel" if delta and delta > 0 else "KpiDown.TLabel" if delta and delta < 0 else "Kpi.TLabel")
        else:
            self.chart.set_data([], empty_text=t("pf.no_data"))

        rows, total_pl, div_total = [], 0.0, 0.0
        for sid, pos in sorted(ctx.positions.items()):
            last = ctx.last_prices.get(sid)
            price = last[1] if last else None
            owned, avg = pos["shares_owned"], pos["avg_buy_price"]
            shorted, avg_s = pos["shares_shorted"], pos["avg_short_price"]
            value = price * owned if price is not None else None
            pl = (price - avg) * owned if price is not None and owned else None
            plp = fmt.change_pct(price, avg) if owned else None
            spl = (avg_s - price) * shorted if price is not None and shorted else None
            total_pl += (pl or 0) + (spl or 0)
            tot = (pl or 0) + (spl or 0)
            div = ctx.dividend_per_min(sid)
            div_total += div or 0.0
            rows.append((sid, (
                sid, fmt.big(owned) if owned else "", fmt.price(avg) if owned else "", fmt.price(price),
                fmt.big(value) if owned else "", fmt.big(pl) if pl is not None else "", fmt.pct(plp) if owned else "",
                fmt.big(shorted) if shorted else "", fmt.price(avg_s) if shorted else "",
                fmt.big(spl) if spl is not None else "", fmt.big(div) if div else "",
            ), dict(stock=sid, owned=owned, avg=avg, price=price, value=value, pl=pl, plp=plp,
                    short=shorted, avg_short=avg_s, short_pl=spl, div_min=div),
                ("up",) if tot > 0 else ("down",) if tot < 0 else ()))
        self.pos_tree.set_rows(rows)
        self.kpi["pl"].configure(text=fmt.big(total_pl) if ctx.positions else "–",
                                 style="KpiUp.TLabel" if total_pl > 0 else "KpiDown.TLabel" if total_pl < 0 else "Kpi.TLabel")

        chg = []
        for ts, sid, owned, avg, shorted, avg_s in db.position_changes(200):
            chg.append((f"{ts}:{sid}", (fmt.clock(ts, with_date=True), sid, fmt.big(owned), fmt.price(avg),
                                       fmt.big(shorted), fmt.price(avg_s)),
                        dict(time=ts, stock=sid, owned=owned, avg=avg, short=shorted, avg_short=avg_s), ()))
        self.chg_tree.set_rows(chg)

        self.kpi["div_min"].configure(text=fmt.big(div_total) if div_total else "–",
                                      style="KpiUp.TLabel" if div_total else "Kpi.TLabel")
        factor = (t("pf.div_factor", f=fmt.num(ctx.div_factor, 2), n=ctx.div_count) if ctx.div_factor
                  else t("pf.div_factor_unknown"))
        self.div_caption.configure(text=(t("pf.div_hour", v=fmt.big(div_total * 60)) + "  ·  " if div_total else "")
                                   + factor)
        self.div_tree.set_rows([
            (str(ts), (fmt.clock(ts, with_date=True), fmt.big(amount), f"×{fmt.num(factor_, 2)}"),
             dict(time=ts, amount=amount, factor=factor_), ("up",))
            for ts, amount, factor_ in db.dividends(limit=300)
        ])


class NewsTab(ttk.Frame):
    NEWS_COLUMNS = [
        ("time", "common.time", 130, "w"),
        ("stock", "common.stock", 80, "w"),
        ("kind", "news.signal", 120, "w"),
        ("price", "news.price", 90, "e"),
        ("lookback", "news.lookback", 80, "e"),
    ]
    SCHED_COLUMNS = [
        ("stock", "common.stock", 80, "w"),
        ("direction", "news.direction", 80, "w"),
        ("target", "news.target", 85, "e"),
        ("scheduled", "news.scheduled_for", 130, "w"),
        ("published", "news.published", 130, "w"),
        ("countdown", "common.status", 110, "e"),
    ]

    def __init__(self, master, app: "App"):
        super().__init__(master, style="Panel.TFrame")
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, style="Panel.TFrame")
        ttk.Label(left, text=t("news.market"), style="Section.TLabel").pack(anchor="w", pady=(6, 2))
        f, self.news_tree = scrolled(left, lambda m: SortableTree(m, self.NEWS_COLUMNS))
        f.pack(fill="both", expand=True)
        right = ttk.Frame(paned, style="Panel.TFrame")
        ttk.Label(right, text=t("news.scheduled"), style="Section.TLabel").pack(anchor="w", pady=(6, 2))
        f, self.sched_tree = scrolled(right, lambda m: SortableTree(m, self.SCHED_COLUMNS))
        f.pack(fill="both", expand=True)
        for tree in (self.news_tree, self.sched_tree):
            tree.tag_configure("up", foreground=THEME["up"])
            tree.tag_configure("down", foreground=THEME["down"])
            tree.tag_configure("past", foreground=THEME["muted"])
        paned.add(left, weight=3)
        paned.add(right, weight=2)
        self.news_tree.sort_col, self.news_tree.sort_desc = "time", True
        self.sched_tree.sort_col, self.sched_tree.sort_desc = "scheduled", True

    def refresh(self, ctx: Ctx) -> None:
        rows = []
        for ts, sid, price, kind, lb in ctx.db.news(limit=500):
            up = kind == "high"
            rows.append((f"{ts}:{sid}:{kind}:{price}", (
                fmt.clock(ts, with_date=True), sid, (t("news.high") if up else t("news.low")) if kind in ("high", "low") else kind,
                fmt.price(price), f"{lb:g} min"),
                dict(time=ts, stock=sid, kind=kind, price=price, lookback=lb), ("up",) if up else ("down",)))
        self.news_tree.set_rows(rows)

        now = ctx.server_now_ms or 0
        rows = []
        for sid, direction, target, sched, pub in ctx.db.scheduled(200):
            future = sched >= now
            status = t("news.in", countdown=fmt.duration((sched - now) / 1000)) if future else t("news.past")
            tag = ("past",) if not future else ("down",) if direction == "crash" else ("up",)
            rows.append((f"{sid}:{sched}:{direction}", (
                sid, direction, fmt.price(target), fmt.clock(sched, with_date=True),
                fmt.clock(pub, with_date=True), status),
                dict(stock=sid, direction=direction, target=target, scheduled=sched, published=pub,
                     countdown=sched - now), tag))
        self.sched_tree.set_rows(rows)


class AutomationTab(ttk.Frame):
    RULE_COLUMNS = [
        ("id", "#", 40, "e"),
        ("stock", "common.stock", 75, "w"),
        ("kind", "auto.type", 105, "w"),
        ("side", "auto.side", 55, "w"),
        ("trigger", "auto.trigger", 230, "w"),
        ("pct", "auto.col_amount", 60, "e"),
        ("price", "common.price", 85, "e"),
        ("dist", "auto.col_distance", 80, "e"),
        ("confirm", "auto.col_confirm", 60, "e"),
        ("repeat", "auto.col_repeat", 65, "center"),
        ("active", "auto.col_active", 50, "center"),
        ("status", "common.status", 260, "w"),
    ]
    LOG_COLUMNS = [
        ("time", "common.time", 130, "w"),
        ("rule", "auto.col_rule", 55, "e"),
        ("stock", "common.stock", 75, "w"),
        ("msg", "auto.col_message", 600, "w"),
    ]
    def __init__(self, master, app: "App"):
        super().__init__(master, style="Panel.TFrame")
        self.app = app
        self._ctx: Optional[Ctx] = None

        top = ttk.Frame(self, style="Panel.TFrame")
        top.pack(fill="x", pady=(8, 4))
        self.enabled_var = tk.BooleanVar(value=app.db.get_setting("automation_enabled", "1") == "1")
        tk.Checkbutton(top, text=t("auto.master"), variable=self.enabled_var, command=self._toggle_master,
                       bg=THEME["panel"], fg=THEME["fg"], selectcolor=THEME["panel_alt"],
                       activebackground=THEME["panel"], activeforeground=THEME["fg"],
                       font=("Segoe UI", 11, "bold"), highlightthickness=0, bd=0).pack(side="left", padx=4)
        self.engine_state = ttk.Label(top, text="", style="Section.TLabel")
        self.engine_state.pack(side="left", padx=12)

        # ---- form
        form = ttk.Frame(self, style="Card.TFrame", padding=(10, 8))
        form.pack(fill="x", padx=4, pady=4)
        self.stock_var = tk.StringVar()
        self.kind_var = tk.StringVar(value=kind_name("stop_loss"))
        self.side_var = tk.StringVar(value=side_name("long"))
        self.value_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=mode_name("pct"))
        self.pct_var = tk.StringVar(value="100")
        self.confirm_var = tk.StringVar(value="0")
        self.repeat_var = tk.BooleanVar(value=False)
        self._editing: Optional[int] = None

        def field(col, title, widget):
            ttk.Label(form, text=title, style="CardMuted.TLabel").grid(row=0, column=col, sticky="w", padx=(0, 10))
            widget.grid(row=1, column=col, sticky="w", padx=(0, 10))
            return widget

        self.stock_cb = field(0, t("common.stock"), ttk.Combobox(form, textvariable=self.stock_var, width=10, state="readonly"))
        self.kind_cb = field(1, t("auto.type"), ttk.Combobox(form, textvariable=self.kind_var, width=14, state="readonly",
                                                            values=[kind_name(k) for k in KIND_KEYS]))
        self.side_cb = field(2, t("auto.side"), ttk.Combobox(form, textvariable=self.side_var, width=7, state="readonly",
                                                            values=[side_name(k) for k in SIDE_KEYS]))
        vf = ttk.Frame(form, style="Card.TFrame")
        self.value_entry = ttk.Entry(vf, textvariable=self.value_var, width=10, justify="right")
        self.value_entry.pack(side="left")
        self.mode_cb = ttk.Combobox(vf, textvariable=self.mode_var, width=15, state="readonly",
                                    values=[mode_name(k) for k in MODE_KEYS])
        self.mode_cb.pack(side="left", padx=(4, 0))
        self.value_label = ttk.Label(form, text=t("auto.trigger"), style="CardMuted.TLabel")
        self.value_label.grid(row=0, column=3, sticky="w", padx=(0, 10))
        vf.grid(row=1, column=3, sticky="w", padx=(0, 10))
        field(4, t("auto.amount_pct"), tk.Spinbox(form, from_=1, to=100, width=5, textvariable=self.pct_var, justify="right",
                                       bg=THEME["panel"], fg=THEME["fg"], buttonbackground=THEME["panel_alt"],
                                       insertbackground=THEME["fg"], relief="flat"))
        field(5, t("auto.confirm_after"), tk.Spinbox(form, from_=0, to=600, width=5, textvariable=self.confirm_var,
                                                   justify="right", bg=THEME["panel"], fg=THEME["fg"],
                                                   buttonbackground=THEME["panel_alt"], insertbackground=THEME["fg"],
                                                   relief="flat"))
        tk.Checkbutton(form, text="↻ " + t("auto.repeat"), variable=self.repeat_var,
                       bg=THEME["panel_alt"], fg=THEME["fg"], selectcolor=THEME["panel"],
                       activebackground=THEME["panel_alt"], activeforeground=THEME["fg"],
                       font=THEME["font_bold"], highlightthickness=0, bd=0).grid(row=1, column=6, padx=(0, 12))
        ttk.Button(form, text=t("auto.use_price"), command=self._use_price).grid(row=1, column=7, padx=(0, 6))
        self.add_btn = tk.Button(form, text=t("auto.add"), command=self._add_rule, bg=THEME["accent"], fg="#0d1117",
                                 activebackground=blend(THEME["accent"], "#ffffff", 0.8), font=THEME["font_bold"],
                                 relief="flat", bd=0, padx=12, pady=3, cursor="hand2")
        self.add_btn.grid(row=1, column=8)
        self.cancel_btn = ttk.Button(form, text=t("auto.cancel_edit"), command=self._cancel_edit)
        self.cancel_btn.grid(row=1, column=9, padx=(6, 0))
        self.cancel_btn.grid_remove()
        self.help = ttk.Label(form, text="", style="CardMuted.TLabel", wraplength=1100, justify="left")
        self.help.grid(row=2, column=0, columnspan=10, sticky="w", pady=(6, 0))
        for var in (self.kind_var, self.side_var, self.mode_var, self.pct_var, self.value_var, self.stock_var,
                    self.repeat_var):
            var.trace_add("write", lambda *_: self._update_form())

        # ---- rules + log
        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, pady=(4, 0))
        rules_frame = ttk.Frame(paned, style="Panel.TFrame")
        bar = ttk.Frame(rules_frame, style="Panel.TFrame")
        bar.pack(fill="x", pady=(2, 2))
        ttk.Label(bar, text=t("auto.rules"), style="Section.TLabel").pack(side="left", padx=4)
        ttk.Button(bar, text=t("auto.delete"), command=self._delete).pack(side="right", padx=2)
        ttk.Button(bar, text=t("auto.toggle"), command=self._toggle_rule).pack(side="right", padx=2)
        ttk.Button(bar, text=t("auto.edit"), command=self._edit_rule).pack(side="right", padx=2)
        ttk.Button(bar, text="↻ " + t("auto.toggle_repeat"), command=self._toggle_repeat).pack(side="right", padx=2)
        f, self.rules_tree = scrolled(rules_frame, lambda m: SortableTree(m, self.RULE_COLUMNS, height=8))
        f.pack(fill="both", expand=True)
        self.rules_tree.tag_configure("off", foreground=THEME["muted"])
        self.rules_tree.tag_configure("armed", foreground=THEME["warn"])
        self.rules_tree.bind("<Double-1>", lambda e: self._toggle_rule())
        self.rules_tree.bind("<Delete>", lambda e: self._delete())
        paned.add(rules_frame, weight=3)

        log_frame = ttk.Frame(paned, style="Panel.TFrame")
        ttk.Label(log_frame, text=t("auto.log"), style="Section.TLabel").pack(anchor="w", padx=4, pady=(6, 2))
        f, self.log_tree = scrolled(log_frame, lambda m: SortableTree(m, self.LOG_COLUMNS, height=6))
        f.pack(fill="both", expand=True)
        self.log_tree.sort_col, self.log_tree.sort_desc = "time", True
        paned.add(log_frame, weight=2)
        self._update_form()

    # ------------------------------------------------------------------- form

    @staticmethod
    def _key(keys, namer, label: str) -> str:
        return next((k for k in keys if namer(k) == label), keys[0])

    def _form_rule(self) -> Optional[dict]:
        try:
            value = float(self.value_var.get().replace(",", "."))
            pct = normalize_percent(float(self.pct_var.get().replace(",", ".")))
            confirm = max(0.0, float(self.confirm_var.get().replace(",", ".")))
        except ValueError:
            return None
        kind = self._key(KIND_KEYS, kind_name, self.kind_var.get())
        mode = "price" if kind in ("buy_limit", "short_limit") else \
            "pct" if kind == "trailing_stop" else self._key(MODE_KEYS, mode_name, self.mode_var.get())
        return dict(id=0, stock_id=self.stock_var.get(), kind=kind, side=self._key(SIDE_KEYS, side_name, self.side_var.get()),
                    mode=mode, value=value, percent=pct, confirm_s=confirm, extreme=None,
                    repeat=int(self.repeat_var.get()), runs=0)

    def _edit_rule(self) -> None:
        rid = self._selected_rule_id()
        r = next((r for r in self._ctx.db.rules() if r["id"] == rid), None) if self._ctx and rid else None
        if not r:
            return
        self._editing = rid
        self.stock_var.set(r["stock_id"])
        self.kind_var.set(kind_name(r["kind"]))
        self.side_var.set(side_name(r["side"]))
        self.mode_var.set(mode_name(r["mode"]))
        self.value_var.set(f"{r['value']:g}".replace(".", fmt.decimal_sep()))
        self.pct_var.set(str(r["percent"]))
        self.confirm_var.set(f"{r['confirm_s']:g}")
        self.repeat_var.set(bool(r["repeat"]))
        self.add_btn.configure(text=t("auto.save"))
        self.cancel_btn.grid()

    def _cancel_edit(self) -> None:
        self._editing = None
        self.add_btn.configure(text=t("auto.add"))
        self.cancel_btn.grid_remove()

    def _update_form(self) -> None:
        kind = self._key(KIND_KEYS, kind_name, self.kind_var.get())
        side = self._key(SIDE_KEYS, side_name, self.side_var.get())
        exit_rule = kind in EXIT_KINDS
        self.side_cb.configure(state="readonly" if exit_rule else "disabled")
        trail, modes = t("mode.trail"), [mode_name(k) for k in MODE_KEYS]
        if kind == "trailing_stop":
            self.mode_cb.configure(state="disabled", values=[trail])
            if self.mode_var.get() != trail:
                self.mode_var.set(trail)
        elif exit_rule:
            self.mode_cb.configure(state="readonly", values=modes)
            if self.mode_var.get() not in modes:
                self.mode_var.set(mode_name("pct"))
        else:
            self.mode_cb.configure(state="disabled", values=[mode_name("price")])
            if self.mode_var.get() != mode_name("price"):
                self.mode_var.set(mode_name("price"))
        below = {"stop_loss": side == "long", "take_profit": side != "long"}.get(kind, True)
        text = t(f"auto.help.{kind}", pct=self.pct_var.get() or "?", side=side_name(side),
                 dir=t("auto.dir_below") if below else t("auto.dir_above"))
        rule = self._form_rule()
        if rule and self._ctx and rule["stock_id"]:
            pos = self._ctx.positions.get(rule["stock_id"])
            last = self._ctx.last_prices.get(rule["stock_id"])
            if kind == "trailing_stop" and last:
                rule["extreme"] = last[1]
            trig = trigger_price(rule, pos)
            text += "\n" + t("auto.current_trigger", trigger=describe_trigger(rule, trig, fmt.price, fmt.decimal_sep()))
            if last:
                text += "   ·   " + t("auto.current_price", price=fmt.price(last[1]))
            if needs_position(rule) and not has_position(rule, pos):
                text += "   ·   " + t("auto.no_position", side=side_name(side), stock=rule["stock_id"])
        text += "\n" + (t("auto.repeat_on_help") if self.repeat_var.get() else t("auto.repeat_off_help"))
        self.help.configure(text=text)

    def _use_price(self) -> None:
        last = self._ctx.last_prices.get(self.stock_var.get()) if self._ctx else None
        if last:
            self.mode_var.set(mode_name("price"))
            self.value_var.set(f"{last[1]:.4f}".rstrip("0").rstrip(".").replace(".", fmt.decimal_sep()))

    def _add_rule(self) -> None:
        rule = self._form_rule()
        if not rule or not rule["stock_id"]:
            messagebox.showwarning(t("auto.rule_title"), t("auto.invalid_form"), parent=self)
            return
        if rule["value"] <= 0 or (rule["mode"] == "pct" and rule["value"] >= 100 and rule["kind"] != "take_profit"):
            messagebox.showwarning(t("auto.rule_title"), t("auto.invalid_value"), parent=self)
            return
        ctx = self._ctx
        last = ctx.last_prices.get(rule["stock_id"]) if ctx else None
        pos = ctx.positions.get(rule["stock_id"]) if ctx else None
        probe = dict(rule, extreme=last[1] if last and rule["kind"] == "trailing_stop" else None)
        trig = trigger_price(probe, pos)
        if last and trig and condition_met(probe, last[1], trig) and \
                (not needs_position(rule) or has_position(rule, pos)) and not messagebox.askyesno(
                    t("auto.rule_title"), t("auto.would_fire", price=fmt.price(last[1])), parent=self):
            return
        if self._editing:
            rid = self._editing
            ctx.db.update_rule(rid, stock_id=rule["stock_id"], kind=rule["kind"], side=rule["side"], mode=rule["mode"],
                               value=rule["value"], percent=rule["percent"], confirm_s=rule["confirm_s"],
                               repeat=rule["repeat"], extreme=None, status=t("rule.st.active"))
            ctx.db.log_rule(int(time.time() * 1000), rid, rule["stock_id"],
                            t("rule.log.edited", kind=kind_name(rule["kind"]),
                              trigger=describe_trigger(rule, None, fmt.price, fmt.decimal_sep()), p=rule["percent"],
                              rep=" ↻" if rule["repeat"] else ""))
            self._cancel_edit()
            self.app.refresh_now()
            return
        rid = ctx.db.add_rule(rule["stock_id"], rule["kind"], rule["side"], rule["mode"], rule["value"],
                              rule["percent"], rule["confirm_s"], int(time.time() * 1000),
                              repeat=bool(rule["repeat"]), status=t("rule.st.active"))
        ctx.db.log_rule(int(time.time() * 1000), rid, rule["stock_id"],
                        t("rule.log.created", kind=kind_name(rule["kind"]),
                          side=side_name(rule["side"]) if rule["kind"] in EXIT_KINDS else "",
                          trigger=describe_trigger(rule, None, fmt.price, fmt.decimal_sep()), p=rule["percent"])
                        + (" ↻" if rule["repeat"] else ""))
        self.app.refresh_now()

    # ------------------------------------------------------------------ rules

    def _selected_rule_id(self) -> Optional[int]:
        sel = self.rules_tree.selection()
        return int(sel[0]) if sel else None

    def _toggle_master(self) -> None:
        on = self.enabled_var.get()
        self.app.db.set_setting("automation_enabled", "1" if on else "0")
        self.app.db.log_rule(int(time.time() * 1000), None, "",
                             t("rule.log.master_on") if on else t("rule.log.master_off"))
        self.app.refresh_now()

    def _toggle_rule(self) -> None:
        rid = self._selected_rule_id()
        if rid is None or not self._ctx:
            return
        rule = next((r for r in self._ctx.db.rules() if r["id"] == rid), None)
        if rule:
            on = not rule["enabled"]
            self._ctx.db.update_rule(rid, enabled=int(on), status=t("rule.st.active") if on else t("rule.st.disabled"),
                                     **({"extreme": None} if on else {}))
            self._ctx.db.log_rule(int(time.time() * 1000), rid, rule["stock_id"],
                                  t("rule.log.enabled") if on else t("rule.log.disabled_manual"))
            self.app.refresh_now()

    def _toggle_repeat(self) -> None:
        rid = self._selected_rule_id()
        if rid is None or not self._ctx:
            return
        rule = next((r for r in self._ctx.db.rules() if r["id"] == rid), None)
        if rule:
            on = not rule["repeat"]
            self._ctx.db.update_rule(rid, repeat=int(on))
            self._ctx.db.log_rule(int(time.time() * 1000), rid, rule["stock_id"],
                                  t("rule.log.repeat_on") if on else t("rule.log.repeat_off"))
            self.app.refresh_now()

    def _delete(self) -> None:
        rid = self._selected_rule_id()
        if rid is None or not self._ctx:
            return
        if messagebox.askyesno(t("auto.delete_title"), t("auto.delete_text", id=rid), parent=self):
            self._ctx.db.delete_rule(rid)
            if self._editing == rid:
                self._cancel_edit()
            self._ctx.db.log_rule(int(time.time() * 1000), rid, "", t("rule.log.deleted"))
            self.app.refresh_now()

    def refresh(self, ctx: Ctx) -> None:
        self._ctx = ctx
        ids = [s["stock_id"] for s in ctx.stocks]
        if list(self.stock_cb.cget("values")) != ids:
            self.stock_cb.configure(values=ids)
        if not self.stock_var.get() and ids:
            self.stock_var.set(self.app.tabs[0].selected or ids[0])

        state = self.app.engine.state
        self.engine_state.configure(
            text=t("engine.label", state=t(f"engine.{state}")),
            foreground=THEME["up"] if state == "active" else THEME["warn"])

        rows = []
        armed = self.app.engine.armed_ids()
        for r in ctx.db.rules():
            pos = ctx.positions.get(r["stock_id"])
            last = ctx.last_prices.get(r["stock_id"])
            price = last[1] if last else None
            trig = trigger_price(r, pos)
            dist = (trig / price - 1) * 100 if trig and price else None
            tags = ("off",) if not r["enabled"] else ("armed",) if r["id"] in armed else ()
            rows.append((str(r["id"]), (
                r["id"], r["stock_id"], kind_name(r["kind"]),
                side_name(r["side"]) if r["kind"] in EXIT_KINDS else "",
                describe_trigger(r, trig, fmt.price, fmt.decimal_sep()), fmt.pct_int(r["percent"]), fmt.price(price), fmt.pct(dist),
                f"{r['confirm_s']:g} s" if r["confirm_s"] else "–",
                t("auto.repeat_cell", n=r["runs"]) if r["repeat"] else t("auto.once_cell", n=r["runs"]),
                "✔" if r["enabled"] else "–", r["status"] or ""),
                dict(id=r["id"], stock=r["stock_id"], kind=r["kind"], side=r["side"], trigger=trig, pct=r["percent"],
                     price=price, dist=dist, confirm=r["confirm_s"], repeat=(r["repeat"], r["runs"]), active=r["enabled"],
                     status=r["status"]),
                tags))
        self.rules_tree.set_rows(rows)

        self.log_tree.set_rows([
            (str(lid), (fmt.clock(ts, with_date=True), f"#{rid}" if rid else "", sid, msg),
             dict(time=lid, rule=rid, stock=sid, msg=msg), ())
            for lid, ts, rid, sid, msg in ctx.db.rule_log(300)
        ])
        self._update_form()


# ------------------------------------------------------------------------- app

class App(tk.Tk):
    def __init__(self, collector: Collector, engine: AutomationEngine, db_path: Path, export_dir: Path):
        super().__init__()
        self.collector = collector
        self.engine = engine
        self.export_dir = export_dir
        self.db = Storage(db_path)
        self.settings = settings_mod.load()
        self.commands: CommandWriter = engine.writer  # shared, so both respect the same rate limit
        self._release: Optional[updater.Release] = None
        self.title(f"{t('app.title')}  v{__version__}")
        self.geometry("1400x900")
        self.minsize(900, 600)
        self.configure(bg=THEME["bg"])
        apply_style(self)
        set_window_icon(self)

        header = ttk.Frame(self, style="Header.TFrame", padding=(10, 8))
        header.pack(fill="x")
        self.hdr: dict[str, ttk.Label] = {}
        for key, title in (("state", t("hdr.state")), ("net", t("common.net_worth")), ("cash", t("common.cash")),
                           ("level", t("common.level")), ("buy", t("hdr.buy_cd")), ("short", t("hdr.short_cd")),
                           ("updated", t("hdr.updated"))):
            box = ttk.Frame(header, style="Header.TFrame")
            box.pack(side="left", padx=(0, 26))
            ttk.Label(box, text=title, style="HeaderMuted.TLabel").pack(anchor="w")
            self.hdr[key] = ttk.Label(box, text="–", style="HeaderValue.TLabel")
            self.hdr[key].pack(anchor="w")
        ttk.Button(header, text=t("common.settings"), style="Header.TButton",
                   command=self._open_settings).pack(side="right")

        # update notice (hidden until a newer release is found)
        self.update_bar = tk.Frame(self, bg=THEME["select"], padx=10, pady=6)
        self.update_label = tk.Label(self.update_bar, text="", bg=THEME["select"], fg=THEME["fg"],
                                     font=THEME["font_bold"])
        self.update_label.pack(side="left")
        bar_btn = dict(relief="flat", bd=0, padx=10, pady=2, cursor="hand2", font=THEME["font"])
        tk.Button(self.update_bar, text=t("update.later"), command=self.update_bar.pack_forget,
                  bg=THEME["panel_alt"], fg=THEME["fg"], **bar_btn).pack(side="right", padx=(6, 0))
        self.install_btn = tk.Button(self.update_bar, text=t("update.install"), command=self._install_update,
                                     bg=THEME["accent"], fg="#0d1117", **bar_btn)
        if settings_mod.is_frozen():  # from source an installer would set up a separate copy
            self.install_btn.pack(side="right", padx=(6, 0))
        tk.Button(self.update_bar, text=t("update.open_page"), bg=THEME["panel_alt"], fg=THEME["fg"],
                  command=lambda: self._release and webbrowser.open(self._release.page_url),
                  **bar_btn).pack(side="right", padx=(6, 0))
        self._header = header

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(6, 0))
        self.tabs = [MarketTab(self.nb, self), CompareTab(self.nb, self), PortfolioTab(self.nb, self),
                     DividendTab(self.nb, self), JournalTab(self.nb, self), StatsTab(self.nb, self),
                     NewsTab(self.nb, self), AutomationTab(self.nb, self)]
        for tab, title in zip(self.tabs, (t("tab.market"), t("tab.compare"), t("tab.portfolio"),
                                            t("tab.dividends"), t("tab.journal"), t("tab.stats"),
                                            t("tab.news"), t("tab.automation"))):
            self.nb.add(tab, text=title)
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self.after_idle(self.refresh_active))

        self.statusbar = ttk.Label(self, text="", style="Status.TLabel", padding=(10, 4))
        self.statusbar.pack(fill="x", side="bottom")

        self._ctx: Optional[Ctx] = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self._tick)
        if self.settings.check_updates:
            self.after(3000, self.check_for_updates)

    # ---------------------------------------------------------------- refresh

    def _build_ctx(self) -> Ctx:
        db = self.db
        status = self.collector.status.copy()
        snap = db.latest_snapshot()
        live = bool(status.last_market_read) and time.time() - status.last_market_read < config.STALE_AFTER_MS / 1000
        server_now = None
        if snap and snap.get("server_ms"):
            server_now = snap["server_ms"]
            if status.last_market_read:
                server_now += int((time.time() - status.last_market_read) * 1000)
        stocks = db.stocks()
        known = {s["stock_id"] for s in stocks}
        stocks += [{"stock_id": sid} for sid in db.stock_ids() if sid not in known]
        ids = [s["stock_id"] for s in stocks]
        if settings_mod.assign_colors(self.settings, ids):
            settings_mod.save(self.settings)
        colors = {sid: self.settings.stock_colors[sid] for sid in ids}
        div_factor, div_count = db.dividend_factor()
        return Ctx(db=db, status=status, snap=snap, end_ms=db.latest_time_ms(), server_now_ms=server_now,
                   live=live, stocks=stocks, positions=db.current_positions(), colors=colors,
                   last_prices={s["stock_id"]: db.latest_price(s["stock_id"]) for s in stocks},
                   div_factor=div_factor, div_count=div_count)

    def _tick(self) -> None:
        try:
            self._ctx = self._build_ctx()
            self._update_header(self._ctx)
            self.refresh_active()
        finally:
            self.after(config.GUI_REFRESH_MS, self._tick)

    def refresh_now(self) -> None:
        """Immediate refresh outside the regular tick (e.g. right after sending a command)."""
        self._ctx = self._build_ctx()
        self._update_header(self._ctx)
        self.refresh_active()

    def refresh_active(self) -> None:
        if not self._ctx:
            return
        idx = self.nb.index(self.nb.select())
        self.tabs[idx].refresh(self._ctx)

    def _update_header(self, ctx: Ctx) -> None:
        st, snap = ctx.status, ctx.snap
        if ctx.live:
            self.hdr["state"].configure(text=t("hdr.live"), style="HeaderLive.TLabel")
        elif not st.market_found:
            self.hdr["state"].configure(text=t("hdr.no_market"), style="HeaderWarn.TLabel")
        else:
            self.hdr["state"].configure(text=t("hdr.paused"), style="HeaderWarn.TLabel")
        if snap:
            self.hdr["net"].configure(text=fmt.big(snap.get("net_worth")))
            self.hdr["cash"].configure(text=fmt.big(snap.get("cash")))
            self.hdr["level"].configure(text=str(snap.get("level") or "–"))
            for key, col in (("buy", "next_buy_ms"), ("short", "next_short_ms")):
                nxt = snap.get(col)
                if nxt and ctx.server_now_ms:
                    rem = (nxt - ctx.server_now_ms) / 1000
                    self.hdr[key].configure(text=t("common.ready") if rem <= 0 else fmt.duration(rem),
                                            style="HeaderLive.TLabel" if rem <= 0 else "HeaderValue.TLabel")
            self.hdr["updated"].configure(text=f"{fmt.clock(ctx.server_now_ms if ctx.live else snap['server_ms'])}"
                                               f"  (#{snap.get('sequence')})")
        counts = ctx.db.counts()
        err = t("status.read_errors", n=st.read_errors, error=st.last_error) if st.read_errors else ""
        self.statusbar.configure(
            text=t("status.bar", src=self.export_dir, db=ctx.db.path.name, prices=fmt.num(counts["prices"], 0),
                   snaps=fmt.num(counts["snapshots"], 0), news=fmt.num(counts["news"], 0),
                   game=st.game_version or "–", version=__version__) + err)

    # --------------------------------------------------------------- settings

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        SettingsDialog(self)

    def apply_settings(self, new: settings_mod.Settings) -> None:
        """Colours and the update switch apply at once; language/folders after a restart."""
        self.settings = new
        self.refresh_now()

    def restart(self) -> None:
        self._on_close()
        settings_mod.restart_app()

    # ---------------------------------------------------------------- updates

    def check_for_updates(self, manual: bool = False, callback=None) -> None:
        """Ask GitHub for the latest release in the background; show the notice if it is newer."""
        def work() -> None:
            try:
                release, error = updater.fetch_latest(), None
            except Exception as exc:
                release, error = None, exc
            self.after(0, lambda: self._update_checked(release, error, callback))

        threading.Thread(target=work, daemon=True).start()

    def _update_checked(self, release, error, callback) -> None:
        newer = release if release and updater.is_newer(release.version) else None
        if newer:
            self._release = newer
            self.update_label.configure(text=t("update.banner", version=newer.version, current=__version__))
            self.install_btn.configure(state="normal" if newer.installer_url else "disabled")
            self.update_bar.pack(fill="x", after=self._header)
        if callback:
            callback(newer, error)

    def _install_update(self) -> None:
        release = self._release
        if not release or not release.installer_url:
            return
        if not messagebox.askyesno(t("update.title"), t("update.confirm", version=release.version), parent=self):
            return
        self.install_btn.configure(state="disabled")

        def progress(done: int, total: int) -> None:
            pct = f" {done * 100 // total} %" if total else ""
            self.after(0, lambda: self.update_label.configure(text=t("update.downloading") + pct))

        def work() -> None:
            try:
                path = updater.download_installer(release, progress)
                self.after(0, lambda: self._run_installer(path))
            except Exception as exc:
                error = exc  # `exc` is cleared when the except block ends
                self.after(0, lambda: self._install_failed(error))

        threading.Thread(target=work, daemon=True).start()

    def _install_failed(self, exc: Exception) -> None:
        self.install_btn.configure(state="normal")
        self.update_label.configure(text=t("update.failed", error=exc))

    def _run_installer(self, path: Path) -> None:
        try:
            updater.launch_installer(path)
        except OSError as exc:
            self._install_failed(exc)
            return
        self._on_close()  # stops automation and recording; the installer starts the new version

    def _on_close(self) -> None:
        self.engine.stop()
        self.collector.stop()
        self.db.close()
        self.destroy()


def run(collector: Collector, engine: AutomationEngine, db_path: Path, export_dir: Path) -> None:
    App(collector, engine, db_path, export_dir).mainloop()
