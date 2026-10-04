"""Analysis tabs: dividend ranking, trade journal and per-stock statistics."""

import time
from tkinter import ttk
from typing import Optional

from ..i18n import t
from . import fmt
from .theme import THEME
from .widgets import RangeBar, SortableTree, scrolled


def _kpi_row(master, items: list[tuple[str, str]]) -> dict[str, ttk.Label]:
    row = ttk.Frame(master, style="Panel.TFrame")
    row.pack(fill="x", pady=(8, 4))
    labels = {}
    for key, title in items:
        box = ttk.Frame(row, style="Card.TFrame", padding=(12, 6))
        box.pack(side="left", padx=4, fill="y")
        ttk.Label(box, text=title, style="CardMuted.TLabel").pack(anchor="w")
        labels[key] = ttk.Label(box, text="–", style="Kpi.TLabel")
        labels[key].pack(anchor="w")
    return labels


def _signed_style(v: Optional[float]) -> str:
    return "KpiUp.TLabel" if v and v > 0 else "KpiDown.TLabel" if v and v < 0 else "Kpi.TLabel"


def _tag(v: Optional[float]) -> tuple:
    return ("up",) if v and v > 0 else ("down",) if v and v < 0 else ()


def _range_window(ctx, rangebar: RangeBar) -> Optional[tuple[int, int]]:
    return ctx.window(rangebar.seconds)


# ------------------------------------------------------------------ dividends

class DividendTab(ttk.Frame):
    """Which stock pays the most dividend per invested money."""

    COLUMNS = [
        ("stock", "common.stock", 80, "w"),
        ("price", "common.price", 85, "e"),
        ("rate", "div.col_rate", 95, "e"),
        ("yield_min", "div.col_yield_min", 105, "e"),
        ("yield_h", "div.col_yield_h", 105, "e"),
        ("per_mio", "div.col_per_mio", 130, "e"),
        ("own", "div.col_own", 110, "e"),
        ("available", "col.available", 100, "e"),
        ("buyable", "div.col_buyable", 85, "center"),
    ]

    def __init__(self, master, app):
        super().__init__(master, style="Panel.TFrame")
        self.app = app
        self.info = ttk.Label(self, text="", style="Section.TLabel", wraplength=1300, justify="left")
        self.info.pack(fill="x", padx=4, pady=(8, 2))
        self.note = ttk.Label(self, text=t("div.note"), style="Muted.TLabel", wraplength=1300, justify="left")
        self.note.pack(fill="x", padx=4, pady=(0, 6))
        f, self.tree = scrolled(self, lambda m: SortableTree(m, self.COLUMNS))
        f.pack(fill="both", expand=True)
        self.tree.sort_col, self.tree.sort_desc = "yield_h", True
        self.tree.tag_configure("own", foreground=THEME["up"])
        self.tree.tag_configure("unavailable", foreground=THEME["muted"])

    def refresh(self, ctx) -> None:
        factor = ctx.div_factor or 1.0
        if ctx.div_factor:
            self.info.configure(text=t("div.info_factor", f=fmt.num(ctx.div_factor, 2), n=ctx.div_count))
        else:
            self.info.configure(text=t("div.info_no_factor"))
        rows = []
        for st in ctx.stocks:
            sid, rate = st["stock_id"], st.get("dividend_rate") or 0.0
            last = ctx.last_prices.get(sid)
            price = last[1] if last else st.get("last_price")
            eff = rate * factor                      # share of the invested money paid per minute
            own = ctx.dividend_per_min(sid)
            avail = st.get("available_shares")
            buyable = bool(avail)
            tags = ("own",) if own else () if buyable else ("unavailable",)
            rows.append((sid, (
                sid, fmt.price(price), fmt.pct(rate * 100, signed=False), fmt.pct(eff * 100, signed=False),
                fmt.pct(eff * 6000, signed=False), fmt.big(1e6 * eff * 60), fmt.big(own) if own else "",
                fmt.big(avail), "✔" if buyable else "✖"),
                dict(stock=sid, price=price, rate=rate, yield_min=eff, yield_h=eff, per_mio=eff,
                     own=own, available=avail, buyable=int(buyable)), tags))
        self.tree.set_rows(rows)


# -------------------------------------------------------------------- journal

class JournalTab(ttk.Frame):
    """Trades with realized P/L (market price at the time of the trade) and summary figures."""

    TRADE_COLUMNS = [
        ("time", "common.time", 125, "w"),
        ("stock", "common.stock", 75, "w"),
        ("kind", "journal.col_kind", 80, "w"),
        ("shares", "journal.col_shares", 95, "e"),
        ("price", "common.price", 85, "e"),
        ("entry", "journal.col_entry", 85, "e"),
        ("pnl", "common.pl", 105, "e"),
        ("pnl_pct", "pf.pl_pct", 80, "e"),
    ]
    STOCK_COLUMNS = [
        ("stock", "common.stock", 80, "w"),
        ("closed", "journal.col_closed", 90, "e"),
        ("wins", "journal.col_wins", 70, "e"),
        ("pnl", "journal.col_realized", 110, "e"),
    ]
    MIN_INTERVAL_S = 5

    def __init__(self, master, app):
        super().__init__(master, style="Panel.TFrame")
        self.app = app
        self._ctx = None
        self._last = 0.0
        self.kpi = _kpi_row(self, [
            ("realized", t("journal.realized")), ("dividends", t("journal.dividends")),
            ("total", t("journal.total")), ("hit", t("journal.hit_rate")),
            ("avg_win", t("journal.avg_win")), ("avg_loss", t("journal.avg_loss")),
            ("best", t("journal.best")), ("worst", t("journal.worst")),
        ])
        bar = ttk.Frame(self, style="Panel.TFrame")
        bar.pack(fill="x", pady=4)
        self.range = RangeBar(bar, self._rerender, default="24h")
        self.range.pack(side="left", padx=4)
        self.note = ttk.Label(bar, text=t("journal.note"), style="Muted.TLabel")
        self.note.pack(side="left", padx=16)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, style="Panel.TFrame")
        ttk.Label(left, text=t("journal.trades"), style="Section.TLabel").pack(anchor="w", pady=(4, 2))
        f, self.trades = scrolled(left, lambda m: SortableTree(m, self.TRADE_COLUMNS))
        f.pack(fill="both", expand=True)
        right = ttk.Frame(paned, style="Panel.TFrame")
        ttk.Label(right, text=t("journal.per_stock"), style="Section.TLabel").pack(anchor="w", pady=(4, 2))
        f, self.per_stock = scrolled(right, lambda m: SortableTree(m, self.STOCK_COLUMNS))
        f.pack(fill="both", expand=True)
        for tree in (self.trades, self.per_stock):
            tree.tag_configure("up", foreground=THEME["up"])
            tree.tag_configure("down", foreground=THEME["down"])
        self.trades.sort_col, self.trades.sort_desc = "time", True
        self.per_stock.sort_col, self.per_stock.sort_desc = "pnl", True
        paned.add(left, weight=3)
        paned.add(right, weight=1)

    def _rerender(self) -> None:
        if self._ctx:
            self._last = 0.0
            self.refresh(self._ctx)

    def refresh(self, ctx) -> None:
        self._ctx = ctx
        if time.time() - self._last < self.MIN_INTERVAL_S:
            return
        self._last = time.time()
        win = _range_window(ctx, self.range)
        trades = []
        if win:
            for st in ctx.stocks:
                trades += ctx.db.trades(st["stock_id"], *win)
        closed = [tr for tr in trades if tr["pnl"] is not None]
        realized = sum(tr["pnl"] for tr in closed)
        dividends = ctx.db.dividend_sum(*win) if win else 0.0
        wins = [tr["pnl"] for tr in closed if tr["pnl"] > 0]
        losses = [tr["pnl"] for tr in closed if tr["pnl"] < 0]

        self.kpi["realized"].configure(text=fmt.big(realized) if closed else "–", style=_signed_style(realized))
        self.kpi["dividends"].configure(text=fmt.big(dividends) if dividends else "–", style=_signed_style(dividends))
        total = realized + dividends
        self.kpi["total"].configure(text=fmt.big(total) if closed or dividends else "–", style=_signed_style(total))
        self.kpi["hit"].configure(
            text=f"{fmt.pct(len(wins) / len(closed) * 100, signed=False)}  ({len(wins)}/{len(closed)})"
            if closed else "–")
        self.kpi["avg_win"].configure(text=fmt.big(sum(wins) / len(wins)) if wins else "–",
                                      style=_signed_style(1 if wins else 0))
        self.kpi["avg_loss"].configure(text=fmt.big(sum(losses) / len(losses)) if losses else "–",
                                       style=_signed_style(-1 if losses else 0))
        best = max(closed, key=lambda tr: tr["pnl"], default=None)
        worst = min(closed, key=lambda tr: tr["pnl"], default=None)
        self.kpi["best"].configure(text=f"{fmt.big(best['pnl'])} {best['stock_id']}" if best else "–",
                                   style=_signed_style(best["pnl"] if best else 0))
        self.kpi["worst"].configure(text=f"{fmt.big(worst['pnl'])} {worst['stock_id']}" if worst else "–",
                                    style=_signed_style(worst["pnl"] if worst else 0))

        rows = []
        for tr in trades:
            pnl = tr["pnl"]
            pct = pnl / (tr["entry"] * tr["shares"]) * 100 if pnl is not None and tr["entry"] else None
            iid = f"{tr['time_ms']}:{tr['stock_id']}:{tr['kind']}"
            rows.append((iid, (
                fmt.clock(tr["time_ms"], with_date=True), tr["stock_id"], t(f"tradekind.{tr['kind']}"),
                fmt.big(tr["shares"]), fmt.price(tr["price"]), fmt.price(tr["entry"]) if tr["entry"] else "",
                fmt.big(pnl) if pnl is not None else "", fmt.pct(pct) if pct is not None else ""),
                dict(time=tr["time_ms"], stock=tr["stock_id"], kind=tr["kind"], shares=tr["shares"],
                     price=tr["price"], entry=tr["entry"], pnl=pnl, pnl_pct=pct), _tag(pnl)))
        self.trades.set_rows(rows)

        per: dict[str, list[float]] = {}
        for tr in closed:
            per.setdefault(tr["stock_id"], []).append(tr["pnl"])
        self.per_stock.set_rows([
            (sid, (sid, len(v), sum(1 for x in v if x > 0), fmt.big(sum(v))),
             dict(stock=sid, closed=len(v), wins=sum(1 for x in v if x > 0), pnl=sum(v)), _tag(sum(v)))
            for sid, v in per.items()
        ])


# ----------------------------------------------------------------- statistics

class StatsTab(ttk.Frame):
    """Volatility, range, behaviour around the base price and after market news."""

    PRICE_COLUMNS = [
        ("stock", "common.stock", 75, "w"),
        ("last", "common.price", 80, "e"),
        ("lo", "stats.col_min", 80, "e"),
        ("hi", "stats.col_max", 80, "e"),
        ("spread", "stats.col_spread", 85, "e"),
        ("vol_min", "stats.col_vol_min", 95, "e"),
        ("vol_h", "stats.col_vol_h", 95, "e"),
        ("base", "col.base", 70, "e"),
        ("dist", "stats.col_dist", 85, "e"),
        ("above", "stats.col_above", 80, "e"),
        ("below", "stats.col_below", 80, "e"),
        ("cross", "stats.col_cross", 90, "e"),
    ]
    NEWS_COLUMNS = [("stock", "common.stock", 75, "w"), ("n_high", "stats.col_n_high", 70, "e")] + [
        (f"h{m}", f"stats.col_high_{m}", 90, "e") for m in (1, 5, 15)] + [
        ("n_low", "stats.col_n_low", 70, "e")] + [(f"l{m}", f"stats.col_low_{m}", 90, "e") for m in (1, 5, 15)]
    MIN_INTERVAL_S = 15

    def __init__(self, master, app):
        super().__init__(master, style="Panel.TFrame")
        self.app = app
        self._ctx = None
        self._last = 0.0
        bar = ttk.Frame(self, style="Panel.TFrame")
        bar.pack(fill="x", pady=(8, 4))
        self.range = RangeBar(bar, self._rerender, default="1h")
        self.range.pack(side="left", padx=4)
        self.updated = ttk.Label(bar, text="", style="Muted.TLabel")
        self.updated.pack(side="left", padx=16)

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True)
        top = ttk.Frame(paned, style="Panel.TFrame")
        ttk.Label(top, text=t("stats.prices"), style="Section.TLabel").pack(anchor="w", pady=(4, 2))
        ttk.Label(top, text=t("stats.prices_note"), style="Muted.TLabel", wraplength=1300,
                  justify="left").pack(anchor="w")
        f, self.prices = scrolled(top, lambda m: SortableTree(m, self.PRICE_COLUMNS, height=9))
        f.pack(fill="both", expand=True)
        bottom = ttk.Frame(paned, style="Panel.TFrame")
        ttk.Label(bottom, text=t("stats.news"), style="Section.TLabel").pack(anchor="w", pady=(6, 2))
        ttk.Label(bottom, text=t("stats.news_note"), style="Muted.TLabel", wraplength=1300,
                  justify="left").pack(anchor="w")
        f, self.news = scrolled(bottom, lambda m: SortableTree(m, self.NEWS_COLUMNS, height=9))
        f.pack(fill="both", expand=True)
        for tree in (self.prices, self.news):
            tree.tag_configure("up", foreground=THEME["up"])
            tree.tag_configure("down", foreground=THEME["down"])
        paned.add(top, weight=1)
        paned.add(bottom, weight=1)

    def _rerender(self) -> None:
        if self._ctx:
            self._last = 0.0
            self.refresh(self._ctx)

    @staticmethod
    def _avg_abs_change(closes: list[tuple[int, float]]) -> Optional[float]:
        changes = [abs(b / a - 1) * 100 for (_, a), (_, b) in zip(closes, closes[1:]) if a]
        return sum(changes) / len(changes) if changes else None

    def refresh(self, ctx) -> None:
        self._ctx = ctx
        if time.time() - self._last < self.MIN_INTERVAL_S:
            return
        self._last = time.time()
        win = _range_window(ctx, self.range)
        db = ctx.db
        price_rows, news_rows = [], []
        for st in ctx.stocks if win else []:
            sid, base = st["stock_id"], st.get("base_price")
            stats = db.range_stats(sid, *win)
            if not stats:
                continue
            lo, hi, _avg, _n = stats
            last = ctx.last_prices.get(sid)
            last_price = last[1] if last else None
            minute = db.bucket_closes(sid, *win, 60_000)
            hourly = db.bucket_closes(sid, *win, 3_600_000)
            vol_min = self._avg_abs_change(minute)
            vol_h = self._avg_abs_change(hourly)
            above = below = cross = None
            dist = fmt.change_pct(last_price, base) if base else None
            if base:
                a, b, n = db.base_split(sid, base, *win)
                above, below = (a / n * 100, b / n * 100) if n else (None, None)
                signs = [1 if p > base else -1 for _, p in minute if p != base]
                cross = sum(1 for x, y in zip(signs, signs[1:]) if x != y)
            price_rows.append((sid, (
                sid, fmt.price(last_price), fmt.price(lo), fmt.price(hi),
                fmt.pct((hi / lo - 1) * 100 if lo else None, signed=False),
                fmt.pct(vol_min, signed=False), fmt.pct(vol_h, signed=False),
                fmt.price(base), fmt.pct(dist), fmt.pct(above, signed=False), fmt.pct(below, signed=False),
                "–" if cross is None else str(cross)),
                dict(stock=sid, last=last_price, lo=lo, hi=hi, spread=(hi / lo - 1) if lo else None,
                     vol_min=vol_min, vol_h=vol_h, base=base, dist=dist, above=above, below=below, cross=cross),
                _tag(dist)))

            # average change after market news, measured from the price in the news item
            effects = {"high": {1: [], 5: [], 15: []}, "low": {1: [], 5: [], 15: []}}
            counts = {"high": 0, "low": 0}
            for ts, _sid, news_price, kind, _lb in db.news(sid, since_ms=win[0], limit=5000):
                if kind not in effects or not news_price or ts > win[1]:
                    continue
                counts[kind] += 1
                for m in (1, 5, 15):
                    if ts + m * 60_000 <= win[1]:
                        later = db.price_at(sid, ts + m * 60_000)
                        if later:
                            effects[kind][m].append((later / news_price - 1) * 100)
            avg = {k: {m: (sum(v) / len(v) if v else None) for m, v in d.items()} for k, d in effects.items()}
            news_rows.append((sid, (
                sid, counts["high"], *[fmt.pct(avg["high"][m]) for m in (1, 5, 15)],
                counts["low"], *[fmt.pct(avg["low"][m]) for m in (1, 5, 15)]),
                dict(stock=sid, n_high=counts["high"], n_low=counts["low"],
                     **{f"h{m}": avg["high"][m] for m in (1, 5, 15)},
                     **{f"l{m}": avg["low"][m] for m in (1, 5, 15)}), ()))
        self.prices.set_rows(price_rows)
        self.news.set_rows(news_rows)
        self.updated.configure(text=t("stats.updated", time=time.strftime("%H:%M:%S"), s=self.MIN_INTERVAL_S))
