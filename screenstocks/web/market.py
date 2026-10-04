"""Market tab of the web UI: watchlist, chart data, trading and order log.

Mixed into Bridge (bridge.py); uses its shared database connection and lock.
Trading follows the classic trade panel exactly: same checks, the shared
CommandWriter of the automation engine (rate limit) and the same evaluation of
the game's command results.
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import config, settings as settings_mod
from ..automation import kind_name, trigger_price
from ..commands import ACTIONS, action_label, action_name, normalize_percent, reason_text, status_text
from ..i18n import t

RANGES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "all": None}
MAX_POINTS = 25_000          # full 1 s resolution up to ~7 h, thinned beyond (detail is loaded on zoom)
TRADE_TIMEOUT_S = 8.0


def _offset(ms: int) -> int:
    """Lightweight Charts shows UTC; shifting by the local offset makes it show local time."""
    return int(datetime.fromtimestamp(ms / 1000).astimezone().utcoffset().total_seconds())


def _points(rows, off: int) -> list[dict]:
    """[(time_ms, value, ...)] -> [{time, value}] with strictly increasing whole seconds."""
    out, last = [], None
    for row in rows:
        ts = row[0] // 1000 + off
        if ts == last:
            out[-1]["value"] = row[1]
            continue
        out.append({"time": ts, "value": row[1]})
        last = ts
    return out


class MarketApi:
    _trade: Optional[dict] = None       # command in flight: SentCommand, known result ids, send time
    _trade_result: Optional[dict] = None

    # ------------------------------------------------------------------ helpers

    def _live(self) -> bool:
        st = self._collector.status.copy()
        return bool(st.last_market_read) and time.time() - st.last_market_read < config.STALE_AFTER_MS / 1000

    def _colors(self, ids: list[str]) -> dict:
        if settings_mod.assign_colors(self._settings, ids):
            settings_mod.save(self._settings)
        return {sid: self._settings.stock_colors[sid] for sid in ids}

    # ---------------------------------------------------------------- watchlist

    def market(self) -> dict:
        """Watchlist rows, trade state and order log (called every second while the tab is open)."""
        if self._closing:
            return {"rows": [], "log": [], "trade": None, "live": False}
        with self._lock:
            db = self._db
            factor, count = db.dividend_factor()
            positions = db.current_positions()
            stocks = db.stocks()
            known = {s["stock_id"] for s in stocks}
            stocks += [{"stock_id": sid} for sid in db.stock_ids() if sid not in known]
            colors = self._colors([s["stock_id"] for s in stocks])
            rows = []
            for st in stocks:
                sid = st["stock_id"]
                last = db.latest_price(sid)
                price = last[1] if last else st.get("last_price")
                t_ref = last[0] if last else None
                deltas = {}
                for key, secs in (("d1", 60), ("d5", 300), ("d15", 900), ("d60", 3600)):
                    old = db.price_at(sid, t_ref - secs * 1000) if t_ref else None
                    deltas[key] = (price / old - 1) * 100 if price and old else None
                spark = [p for _, p in db.bucket_closes(sid, t_ref - 30 * 60_000, t_ref, 30_000)] if t_ref else []
                pos = positions.get(sid, {})
                owned, avg = pos.get("shares_owned", 0.0), pos.get("avg_buy_price", 0.0)
                shorted, avg_s = pos.get("shares_shorted", 0.0), pos.get("avg_short_price", 0.0)
                pl = (price - avg) * owned + (avg_s - price) * shorted if price and (owned or shorted) else None
                rate = st.get("dividend_rate") or 0.0
                div = owned * price * rate * (factor or 1.0) if owned and price and rate else None
                rows.append(dict(id=sid, name=st.get("name") or sid, color=colors[sid], price=price, **deltas,
                                 spark=spark, base=st.get("base_price"), cap=st.get("price_cap"), rate=rate,
                                 avail=st.get("available_shares"), maxvol=st.get("max_volume"),
                                 unlocked=bool(st.get("unlocked", 1)), owned=owned, avg=avg, shorted=shorted,
                                 avg_short=avg_s, pl=pl, div=div))
            log = [dict(id=r["id"], time=r["finished_ms"] or r["received_ms"], stock=r["stock_id"],
                        action=action_label(r["action"]), pct=r["percent"], status=r["status"],
                        status_text=status_text(r["status"]), reason=reason_text(r["reason"]))
                   for r in db.command_results(100)]
        return {"rows": rows, "factor": factor, "factor_n": count, "live": self._live(),
                "trade": self._trade_status(), "log": log}

    # -------------------------------------------------------------------- chart

    def series(self, stock_id: str, range_key: str) -> dict:
        """Price series of the selected range plus markers, reference lines and announced events."""
        empty = {"data": [], "markers": [], "news": [], "lines": [], "events": [], "last_ms": 0, "offset": 0}
        if self._closing:
            return empty
        with self._lock:
            db = self._db
            end = db.latest_time_ms()
            if end is None:
                return empty
            first = db.first_time_ms() or end
            secs = RANGES.get(range_key)
            since = first if secs is None else max(first, end - secs * 1000)
            off = _offset(end)
            pts = db.price_series(stock_id, since, end, max_points=MAX_POINTS)
            bucket = max(1, (end - since) // MAX_POINTS)
            markers = [dict(time=tr["time_ms"] // 1000 + off, kind=tr["kind"], price=tr["price"],
                            letter=t(f"tradekind.{tr['kind']}.letter"),
                            text=t("market.trade_marker", kind=t(f"tradekind.{tr['kind']}"),
                                   shares=f"{tr['shares']:,.0f}", price=f"{tr['price']:.4g}"))
                       for tr in db.trades(stock_id, since, end) if tr["price"]]
            news = [dict(time=ts // 1000 + off, kind=kind, price=p)
                    for ts, _s, p, kind, _lb in db.news(stock_id, since_ms=since, limit=2000)]
            positions = db.current_positions()
            pos = positions.get(stock_id)
            lines = []
            if pos and pos["shares_owned"]:
                lines.append(dict(price=pos["avg_buy_price"], kind="avg_buy", title=t("common.avg_buy")))
            if pos and pos["shares_shorted"]:
                lines.append(dict(price=pos["avg_short_price"], kind="avg_short", title=t("common.avg_short")))
            for rule in db.rules(enabled_only=True):
                if rule["stock_id"] == stock_id:
                    trig = trigger_price(rule, pos)
                    if trig:
                        lines.append(dict(price=trig, kind=rule["kind"], title=f"{kind_name(rule['kind'])} #{rule['id']}"))
            snap = db.latest_snapshot() or {}
            now = snap.get("server_ms") or end
            events = []
            for s, direction, target, at, _pub in db.scheduled(50):
                if s == stock_id and at >= now:
                    lines.append(dict(price=target, kind="event", title=t("market.scheduled_line", direction=direction)))
                    events.append(dict(direction=direction, target=target, at=at))
        return {"data": _points(pts, off), "markers": markers, "news": news, "lines": lines,
                "events": sorted(events, key=lambda e: e["at"]), "last_ms": end, "offset": off,
                "bucket_ms": int(bucket)}

    def series_detail(self, stock_id: str, from_s: int, to_s: int, offset: int) -> dict:
        """Full-resolution points for a zoomed window (chart times are local-shifted seconds)."""
        since, until = (int(from_s) - offset) * 1000, (int(to_s) - offset) * 1000 + 999
        with self._lock:
            pts = self._db.price_series(stock_id, since, until, max_points=MAX_POINTS)
        return {"data": _points(pts, offset), "bucket_ms": int(max(1, (until - since) // MAX_POINTS))}

    def updates(self, stock_id: str, since_ms: int) -> dict:
        """New price points after since_ms (live append)."""
        if self._closing:
            return {"data": [], "last_ms": since_ms}
        with self._lock:
            rows = self._db.conn.execute(
                "SELECT time_ms, price FROM prices WHERE stock_id=? AND time_ms>? ORDER BY time_ms LIMIT 5000",
                (stock_id, int(since_ms))).fetchall()
        if not rows:
            return {"data": [], "last_ms": since_ms}
        return {"data": _points(rows, _offset(rows[-1][0])), "last_ms": rows[-1][0]}

    # ------------------------------------------------------------------- trading

    def trade(self, stock_id: str, action: str, percent: float) -> dict:
        """Send a trade command. Returns {"ok": bool, "text": message} (same checks as the classic panel)."""
        if action not in ACTIONS:
            return {"ok": False, "text": t("cmd.unknown_action", action=action)}
        try:
            pct = normalize_percent(float(percent))
        except (TypeError, ValueError):
            return {"ok": False, "text": t("trade.invalid_pct")}
        if not self._live():
            return {"ok": False, "text": t("trade.not_live_short")}
        if self._trade:
            return {"ok": False, "text": t("trade.busy")}
        writer = self._engine.writer
        if writer.commands_enabled() is False:
            return {"ok": False, "text": t("trade.commands_disabled")}
        with self._lock:
            known = {r["id"] for r in self._db.command_results(200)}
        try:
            sent = writer.send(stock_id, action, pct)
        except Exception as exc:
            return {"ok": False, "text": t("common.error", error=exc)}
        self._trade = {"sent": sent, "known": known, "at": time.time()}
        self._trade_result = {"state": "sent", "kind": "warn",
                              "text": t("trade.sent", action=action_name(action), p=pct, stock=stock_id)}
        return {"ok": True, "text": self._trade_result["text"]}

    def _trade_status(self) -> Optional[dict]:
        """Evaluate the command in flight (like TradePanel._check_pending)."""
        pending = self._trade
        if pending:
            sent = pending["sent"]
            label = action_name(sent.action)
            with self._lock:
                new = [r for r in self._db.command_results(50)
                       if r["id"] not in pending["known"] and r["stock_id"] == sent.stock_id
                       and (r["action"] or "").startswith(ACTIONS[sent.action])]
            if new:
                r = new[0]
                text = t("trade.result", action=label, p=sent.percent, stock=sent.stock_id,
                         status=status_text(r["status"]))
                reason = reason_text(r["reason"])
                if reason:
                    text += f" – {reason}"
                if r["status"] == "done":
                    self._trade_result = {"state": "done", "kind": "ok", "text": "✔ " + text}
                    self._trade = None
                elif r["status"] in ("rejected", "failed"):
                    self._trade_result = {"state": "rejected", "kind": "err", "text": "✖ " + text}
                    self._trade = None
                else:
                    self._trade_result = {"state": "running", "kind": "warn", "text": "… " + text}
            elif time.time() - pending["at"] > TRADE_TIMEOUT_S:
                disarmed = self._engine.writer.cancel(sent)
                self._trade = None
                self._trade_result = {"state": "timeout", "kind": "err",
                                      "text": t("trade.not_picked_up") if disarmed else t("trade.no_response")}
        return self._trade_result

    # -------------------------------------------------------------------- export

    def export_csv(self, range_key: str) -> dict:
        """Save the prices of the selected range as CSV (native save dialog)."""
        import webview
        with self._lock:
            end = self._db.latest_time_ms()
            first = self._db.first_time_ms()
        if end is None:
            return {"ok": False, "text": t("export.none")}
        secs = RANGES.get(range_key)
        since = first if secs is None else max(first, end - secs * 1000)
        name = f"screenstocks_{range_key}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        result = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=name,
                                                 file_types=("CSV (*.csv)",))
        if not result:
            return {"ok": False, "text": ""}
        path = Path(result if isinstance(result, str) else result[0])
        with self._lock:
            n = self._db.export_prices_csv(path, since, end)
        return {"ok": True, "text": t("export.done", n=f"{n:,}", path=path)}
