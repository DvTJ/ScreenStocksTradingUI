"""Portfolio, Dividends and Journal tabs of the web UI.

Mixed into Bridge (bridge.py). The figures are computed exactly like the classic
PortfolioTab, DividendTab and JournalTab; formatting happens in the browser.
"""

from datetime import datetime
from typing import Optional

RANGES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "all": None}


def _offset(ms: int) -> int:
    return int(datetime.fromtimestamp(ms / 1000).astimezone().utcoffset().total_seconds())


def _window(range_key: str, first: Optional[int], end: Optional[int]) -> Optional[tuple[int, int]]:
    """Never reach back further than the recorded history (same as Ctx.window in the classic UI)."""
    if end is None:
        return None
    first = first or end
    secs = RANGES.get(range_key)
    return (first if secs is None else max(first, end - secs * 1000)), end


class PortfolioApi:
    # ---------------------------------------------------------------- portfolio

    def portfolio(self, range_key: str) -> dict:
        """KPIs, positions, position changes and dividend payouts (every second while open)."""
        if self._closing:
            return {}
        with self._lock:
            db = self._db
            snap = db.latest_snapshot() or {}
            net, cash = snap.get("net_worth"), snap.get("cash")
            first = db.conn.execute("SELECT MIN(server_ms) FROM snapshots").fetchone()[0]
            win = _window(range_key, first, snap.get("server_ms"))
            factor, count = db.dividend_factor()
            start_net = received = None
            if win:
                received = db.dividend_sum(*win)
                start_net = db.snapshot_value_at("net_worth", win[0])
            rates = {s["stock_id"]: s.get("dividend_rate") or 0.0 for s in db.stocks()}
            positions, open_pl, div_total = [], 0.0, 0.0
            for sid, pos in sorted(db.current_positions().items()):
                last = db.latest_price(sid)
                price = last[1] if last else None
                owned, avg = pos["shares_owned"], pos["avg_buy_price"]
                shorted, avg_s = pos["shares_shorted"], pos["avg_short_price"]
                pl = (price - avg) * owned if price is not None and owned else None
                spl = (avg_s - price) * shorted if price is not None and shorted else None
                div = owned * price * rates.get(sid, 0) * (factor or 1.0) if owned and price else None
                open_pl += (pl or 0) + (spl or 0)
                div_total += div or 0.0
                positions.append(dict(stock=sid, owned=owned, avg=avg, price=price,
                                      value=price * owned if price is not None and owned else None,
                                      pl=pl, plp=(price / avg - 1) * 100 if owned and price and avg else None,
                                      short=shorted, avg_short=avg_s, short_pl=spl, div=div))
            changes = [dict(time=ts, stock=sid, owned=o, avg=a, short=s, avg_short=sa)
                       for ts, sid, o, a, s, sa in db.position_changes(200)]
            payouts = [dict(time=ts, amount=amount, factor=f) for ts, amount, f in db.dividends(limit=300)]
        delta = net - start_net if net is not None and start_net is not None else None
        return {"net": net, "cash": cash, "invested": net - cash if net is not None and cash is not None else None,
                "delta": delta, "delta_pct": (net / start_net - 1) * 100 if delta is not None and start_net else None,
                "open_pl": open_pl if positions else None, "div_min": div_total or None,
                "received": received or None, "factor": factor, "factor_n": count,
                "positions": positions, "changes": changes, "payouts": payouts}

    def portfolio_chart(self, range_key: str) -> dict:
        """Net worth and cash over the range (snapshot/server time)."""
        if self._closing:
            return {"net": [], "cash": []}
        with self._lock:
            db = self._db
            snap = db.latest_snapshot() or {}
            first = db.conn.execute("SELECT MIN(server_ms) FROM snapshots").fetchone()[0]
            win = _window(range_key, first, snap.get("server_ms"))
            rows = db.portfolio_series(*win, max_points=20_000) if win else []
        if not rows:
            return {"net": [], "cash": []}
        off = _offset(rows[-1][0])
        net, cash, last = [], [], None
        for ts, n, c in rows:
            sec = ts // 1000 + off
            if sec == last:
                continue
            last = sec
            net.append({"time": sec, "value": n})
            cash.append({"time": sec, "value": c})
        return {"net": net, "cash": cash, "offset": off}

    # ---------------------------------------------------------------- dividends

    def dividend_ranking(self) -> dict:
        """Dividend yield per invested money for every stock (classic DividendTab)."""
        if self._closing:
            return {"rows": []}
        with self._lock:
            db = self._db
            factor, count = db.dividend_factor()
            f = factor or 1.0
            positions = db.current_positions()
            rows = []
            for st in db.stocks():
                sid, rate = st["stock_id"], st.get("dividend_rate") or 0.0
                last = db.latest_price(sid)
                price = last[1] if last else st.get("last_price")
                owned = (positions.get(sid) or {}).get("shares_owned") or 0.0
                eff = rate * f                     # share of the invested money paid per minute
                rows.append(dict(stock=sid, price=price, rate=rate * 100, yield_min=eff * 100, yield_h=eff * 6000,
                                 per_mio=1e6 * eff * 60, own=owned * price * eff if owned and price else None,
                                 available=st.get("available_shares"), buyable=bool(st.get("available_shares"))))
        return {"factor": factor, "factor_n": count, "rows": rows}

    # ------------------------------------------------------------------ journal

    def journal(self, range_key: str) -> dict:
        """Trades with realized P/L (market price at trade time), summary and P/L per stock."""
        if self._closing:
            return {}
        with self._lock:
            db = self._db
            win = _window(range_key, db.first_time_ms(), db.latest_time_ms())
            trades = []
            if win:
                for sid in db.stock_ids():
                    trades += db.trades(sid, *win)
            dividends = db.dividend_sum(*win) if win else 0.0
        closed = [tr for tr in trades if tr["pnl"] is not None]
        realized = sum(tr["pnl"] for tr in closed)
        wins = [tr["pnl"] for tr in closed if tr["pnl"] > 0]
        losses = [tr["pnl"] for tr in closed if tr["pnl"] < 0]
        best = max(closed, key=lambda tr: tr["pnl"], default=None)
        worst = min(closed, key=lambda tr: tr["pnl"], default=None)
        per: dict[str, list[float]] = {}
        for tr in closed:
            per.setdefault(tr["stock_id"], []).append(tr["pnl"])
        rows = []
        for tr in trades:
            pnl = tr["pnl"]
            rows.append(dict(time=tr["time_ms"], stock=tr["stock_id"], kind=tr["kind"], shares=tr["shares"],
                             price=tr["price"], entry=tr["entry"], pnl=pnl,
                             pnl_pct=pnl / (tr["entry"] * tr["shares"]) * 100 if pnl is not None and tr["entry"] else None))
        return {
            "realized": realized if closed else None, "dividends": dividends or None,
            "total": (realized + dividends) if closed or dividends else None,
            "closed": len(closed), "wins": len(wins),
            "hit_rate": len(wins) / len(closed) * 100 if closed else None,
            "avg_win": sum(wins) / len(wins) if wins else None,
            "avg_loss": sum(losses) / len(losses) if losses else None,
            "best": {"pnl": best["pnl"], "stock": best["stock_id"]} if best else None,
            "worst": {"pnl": worst["pnl"], "stock": worst["stock_id"]} if worst else None,
            "trades": rows,
            "per_stock": [dict(stock=sid, closed=len(v), wins=sum(1 for x in v if x > 0), pnl=sum(v))
                          for sid, v in per.items()],
        }
