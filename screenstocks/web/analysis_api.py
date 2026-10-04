"""Compare, Statistics and News tabs of the web UI.

Mixed into Bridge (bridge.py). The figures are computed exactly like the classic
CompareTab, StatsTab and NewsTab; formatting happens in the browser.
"""

import time
from typing import Optional

from .market import RANGES, _offset

COMPARE_POINTS = 2000        # per stock and reload; deep zooms load full detail via compare_detail


def _avg_abs_change(closes: list[tuple[int, float]]) -> Optional[float]:
    changes = [abs(b / a - 1) * 100 for (_, a), (_, b) in zip(closes, closes[1:]) if a]
    return sum(changes) / len(changes) if changes else None


def _norm(rows, base: float, off: int) -> list[dict]:
    """[(time_ms, value, ...)] -> % change against base, strictly increasing whole seconds."""
    out, last = [], None
    for row in rows:
        ts = row[0] // 1000 + off
        v = (row[1] / base - 1) * 100
        if ts == last:
            out[-1]["value"] = v
            continue
        out.append({"time": ts, "value": v})
        last = ts
    return out


class AnalysisApi:
    @staticmethod
    def _price_window(db, range_key: str) -> Optional[tuple[int, int]]:
        """Same as Ctx.window in the classic UI: never further back than the recorded prices."""
        end = db.latest_time_ms()
        if end is None:
            return None
        first = db.first_time_ms() or end
        secs = RANGES.get(range_key)
        return (first if secs is None else max(first, end - secs * 1000)), end

    def _stock_ids(self) -> list[str]:
        stocks = self._db.stocks()
        known = {s["stock_id"] for s in stocks}
        return [s["stock_id"] for s in stocks] + [sid for sid in self._db.stock_ids() if sid not in known]

    # ------------------------------------------------------------------ compare

    def compare(self, range_key: str) -> dict:
        """All stocks normalised to % change since the start of the range."""
        if self._closing:
            return {"stocks": [], "offset": 0}
        with self._lock:
            db = self._db
            ids = self._stock_ids()
            colors = self._colors(ids)
            win = self._price_window(db, range_key)
            if not win:
                return {"stocks": [dict(id=sid, color=colors[sid], base=None, data=[]) for sid in ids], "offset": 0}
            off = _offset(win[1])
            stocks = []
            for sid in ids:
                pts = db.price_series(sid, *win, max_points=COMPARE_POINTS)
                base = (db.price_at(sid, win[0]) or pts[0][1]) if pts else None
                stocks.append(dict(id=sid, color=colors[sid], base=base,
                                   data=_norm(pts, base, off) if base else []))
        return {"stocks": stocks, "offset": off, "bucket_ms": int(max(1, (win[1] - win[0]) // COMPARE_POINTS))}

    def compare_detail(self, from_s: int, to_s: int, offset: int, bases: dict) -> dict:
        """Full-resolution points of a zoomed window, normalised with the bases of the full range."""
        since, until = (int(from_s) - offset) * 1000, (int(to_s) - offset) * 1000 + 999
        with self._lock:
            return {sid: _norm(self._db.price_series(sid, since, until, max_points=COMPARE_POINTS * 4), base, offset)
                    for sid, base in bases.items() if base}

    # --------------------------------------------------------------- statistics

    def statistics(self, range_key: str) -> dict:
        """Price behaviour (volatility, range, base price) and the average move after market news."""
        if self._closing:
            return {"prices": [], "news": []}
        with self._slow_lock:                 # own connection: takes up to ~2 s for long ranges
            db = self._slow_db
            win = self._price_window(db, range_key)
            prices, news = [], []
            for st in db.stocks() if win else []:
                sid, base = st["stock_id"], st.get("base_price")
                stats = db.range_stats(sid, *win)
                if not stats or not stats[3]:
                    continue
                lo, hi, _avg, _n = stats
                last = db.latest_price(sid)
                last_price = last[1] if last else None
                minute = db.bucket_closes(sid, *win, 60_000)
                hourly = db.bucket_closes(sid, *win, 3_600_000)
                above = below = cross = None
                dist = (last_price / base - 1) * 100 if base and last_price else None
                if base:
                    a, b, n = db.base_split(sid, base, *win)
                    above, below = (a / n * 100, b / n * 100) if n else (None, None)
                    signs = [1 if p > base else -1 for _, p in minute if p != base]
                    cross = sum(1 for x, y in zip(signs, signs[1:]) if x != y)
                prices.append(dict(stock=sid, last=last_price, lo=lo, hi=hi,
                                   spread=(hi / lo - 1) * 100 if lo else None,
                                   vol_min=_avg_abs_change(minute), vol_h=_avg_abs_change(hourly),
                                   base=base, dist=dist, above=above, below=below, cross=cross))

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
                news.append(dict(stock=sid, n_high=counts["high"], n_low=counts["low"],
                                 **{f"h{m}": avg["high"][m] for m in (1, 5, 15)},
                                 **{f"l{m}": avg["low"][m] for m in (1, 5, 15)}))
        return {"prices": prices, "news": news, "calculated": int(time.time() * 1000)}

    # --------------------------------------------------------------------- news

    def news(self) -> dict:
        """Market news (high/low alerts) and scheduled events; the countdown runs in the page."""
        if self._closing:
            return {"news": [], "scheduled": []}
        with self._lock:
            db = self._db
            snap = db.latest_snapshot() or {}
            server_now = snap.get("server_ms")
            st = self._collector.status.copy()
            if server_now and st.last_market_read:
                server_now += int((time.time() - st.last_market_read) * 1000)
            news = [dict(time=ts, stock=sid, kind=kind, price=price, lookback=lb)
                    for ts, sid, price, kind, lb in db.news(limit=500)]
            scheduled = [dict(stock=sid, direction=direction, target=target, scheduled=at, published=pub)
                         for sid, direction, target, at, pub in db.scheduled(200)]
            colors = self._colors(self._stock_ids())
        return {"news": news, "scheduled": scheduled, "server_now": server_now, "colors": colors}
