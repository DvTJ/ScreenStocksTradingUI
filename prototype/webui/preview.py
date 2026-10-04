"""Design preview of a web-based Market tab (pywebview + TradingView Lightweight Charts).

Read-only: opens the recorded database without write access and never sends
commands to the game. Run with the installed app (or `python main.py`) recording
in the background to see live data:

    pip install pywebview
    python prototype/webui/preview.py
"""

import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402

from screenstocks import __version__, settings as settings_mod  # noqa: E402
from screenstocks.i18n import set_language, system_language  # noqa: E402
from screenstocks.storage import Storage  # noqa: E402
from screenstocks.automation import kind_name, trigger_price  # noqa: E402

HERE = Path(__file__).resolve().parent
RANGES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "all": None}


def open_readonly(path: Path) -> Storage:
    """A Storage object on a read-only connection (skips schema/migrations, never writes)."""
    st = Storage.__new__(Storage)
    st.path = Path(path)
    st.conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, check_same_thread=False)
    st._pos_cache = None
    st._prev_cash = None
    return st


def tz_offset_s(ms: int) -> int:
    """Lightweight Charts shows UTC; shifting by the local offset makes it show local time."""
    return int(datetime.fromtimestamp(ms / 1000).astimezone().utcoffset().total_seconds())


class Api:
    def __init__(self, db_path: Path, settings: settings_mod.Settings):
        self.db = open_readonly(db_path)
        self.settings = settings
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ helpers

    def _ctx(self):
        db = self.db
        snap = db.latest_snapshot() or {}
        now_local = time.time() * 1000
        written = snap.get("written_ms") or 0
        live = bool(written) and now_local - written < 5000
        server_now = (snap.get("server_ms") or 0) + (now_local - written if live else 0)
        stocks = db.stocks()
        return db, snap, live, int(server_now), stocks, db.current_positions()

    # --------------------------------------------------------------------- api

    def init(self) -> dict:
        return {"lang": self.settings.language or system_language(), "version": __version__,
                "colors": self.settings.stock_colors, "db": str(self.db.path)}

    def snapshot(self) -> dict:
        with self.lock:
            db, snap, live, now, stocks, positions = self._ctx()
            factor, count = db.dividend_factor()
            rows = []
            for st in stocks:
                sid = st["stock_id"]
                last = db.latest_price(sid)
                price = last[1] if last else st.get("last_price")
                t_ref = last[0] if last else now
                deltas = {}
                for key, secs in (("d1", 60), ("d5", 300), ("d15", 900), ("d60", 3600)):
                    old = db.price_at(sid, t_ref - secs * 1000)
                    deltas[key] = (price / old - 1) * 100 if price and old else None
                spark = [p for _, p in db.bucket_closes(sid, t_ref - 30 * 60_000, t_ref, 30_000)]
                pos = positions.get(sid, {})
                owned, avg = pos.get("shares_owned", 0.0), pos.get("avg_buy_price", 0.0)
                shorted, avg_s = pos.get("shares_shorted", 0.0), pos.get("avg_short_price", 0.0)
                pl = (price - avg) * owned + (avg_s - price) * shorted if price and (owned or shorted) else None
                div = owned * price * (st.get("dividend_rate") or 0) * (factor or 1) if owned and price else None
                rows.append(dict(id=sid, name=st.get("name") or sid, price=price, **deltas, spark=spark,
                                 base=st.get("base_price"), cap=st.get("price_cap"), rate=st.get("dividend_rate"),
                                 avail=st.get("available_shares"), owned=owned, avg=avg, shorted=shorted,
                                 avg_short=avg_s, pl=pl, div=div))
            return dict(live=live, now=now, cash=snap.get("cash"), net=snap.get("net_worth"), level=snap.get("level"),
                        buy_cd=((snap.get("next_buy_ms") or 0) - now) / 1000,
                        short_cd=((snap.get("next_short_ms") or 0) - now) / 1000,
                        factor=factor, factor_n=count, rows=rows)

    def series(self, sid: str, range_key: str) -> dict:
        with self.lock:
            db, snap, live, now, stocks, positions = self._ctx()
            end = db.latest_time_ms() or now
            secs = RANGES.get(range_key)
            first = db.first_time_ms() or end
            since = first if secs is None else max(first, end - secs * 1000)
            off = tz_offset_s(end)
            # full resolution up to ~6 h, then thinned (the chart zooms client-side)
            pts = db.price_series(sid, since, end, max_points=25_000)
            data, last_t = [], None
            for t, v, _lo, _hi in pts:
                ts = t // 1000 + off
                if ts == last_t:          # Lightweight Charts needs strictly increasing times
                    data[-1]["value"] = v
                    continue
                data.append({"time": ts, "value": v})
                last_t = ts
            markers = []
            for tr in db.trades(sid, since, end):
                if tr["price"]:
                    markers.append({"time": tr["time_ms"] // 1000 + off, "kind": tr["kind"], "price": tr["price"],
                                    "shares": tr["shares"], "pnl": tr["pnl"]})
            news = [{"time": ts // 1000 + off, "kind": kind, "price": p}
                    for ts, _s, p, kind, _lb in db.news(sid, since_ms=since)]
            lines = []
            pos = positions.get(sid)
            if pos and pos["shares_owned"]:
                lines.append({"price": pos["avg_buy_price"], "kind": "avg_buy"})
            if pos and pos["shares_shorted"]:
                lines.append({"price": pos["avg_short_price"], "kind": "avg_short"})
            for rule in db.rules(enabled_only=True):
                if rule["stock_id"] == sid:
                    trig = trigger_price(rule, pos)
                    if trig:
                        lines.append({"price": trig, "kind": "rule", "label": f"{kind_name(rule['kind'])} #{rule['id']}"})
            events = [{"direction": d, "target": tgt, "at": ms, "in_s": (ms - now) / 1000}
                      for s, d, tgt, ms, _pub in db.scheduled(50) if s == sid and ms >= now]
            return dict(data=data, markers=markers, news=news, lines=lines, events=events, last_ms=end, offset=off)

    def open_url(self, url: str) -> None:
        """Open links (e.g. the TradingView attribution) in the default browser."""
        if url.startswith("https://www.tradingview.com/"):
            import webbrowser
            webbrowser.open(url)

    def updates(self, sid: str, since_ms: int) -> dict:
        """New price points after since_ms (live append)."""
        with self.lock:
            rows = self.db.conn.execute(
                "SELECT time_ms, price FROM prices WHERE stock_id=? AND time_ms>? ORDER BY time_ms",
                (sid, int(since_ms))).fetchall()
            if not rows:
                return {"data": [], "last_ms": since_ms}
            off = tz_offset_s(rows[-1][0])
            return {"data": [{"time": t // 1000 + off, "value": p} for t, p in rows], "last_ms": rows[-1][0]}


def main() -> None:
    settings = settings_mod.load()
    set_language(settings.language or system_language())
    api = Api(settings.db_file, settings)
    webview.create_window("ScreenStocks – Market (design preview)", str(HERE / "index.html"), js_api=api,
                          width=1500, height=920, min_size=(1100, 700), background_color="#111214")
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
