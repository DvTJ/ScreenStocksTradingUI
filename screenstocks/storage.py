"""SQLite history of everything read from the export files.

Every thread opens its own Storage instance; WAL mode lets the GUI read
while the collector writes.
"""

import bisect
import csv
import os
import sqlite3
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .reader import MarketSnapshot, PriceSample

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    stock_id         TEXT PRIMARY KEY,
    name             TEXT,
    unlocked         INTEGER,
    base_price       REAL,
    price_cap        REAL,
    dividend_rate    REAL,
    max_volume       INTEGER,
    available_shares INTEGER,
    last_price       REAL,
    updated_ms       INTEGER
);

-- One price per stock and server tick (server time in ms).
CREATE TABLE IF NOT EXISTS prices (
    stock_id TEXT    NOT NULL,
    tick     INTEGER NOT NULL,
    time_ms  INTEGER NOT NULL,
    price    REAL    NOT NULL,
    PRIMARY KEY (stock_id, tick)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_prices_time ON prices (stock_id, time_ms);

-- Player state per market.json write.
CREATE TABLE IF NOT EXISTS snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence          INTEGER,
    written_ms        INTEGER,
    server_ms         INTEGER,
    server_tick       INTEGER,
    market_ready      INTEGER,
    cash              REAL,
    net_worth         REAL,
    level             INTEGER,
    ipo_count         INTEGER,
    next_buy_ms       INTEGER,
    next_short_ms     INTEGER,
    buy_cooldown_s    REAL,
    short_cooldown_s  REAL,
    game_version      TEXT,
    UNIQUE (written_ms, sequence)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_server ON snapshots (server_ms);

-- Position rows are only written when a position changes.
CREATE TABLE IF NOT EXISTS position_history (
    server_ms      INTEGER NOT NULL,
    stock_id       TEXT    NOT NULL,
    shares_owned   REAL,
    avg_buy_price  REAL,
    shares_shorted REAL,
    avg_short_price REAL,
    PRIMARY KEY (stock_id, server_ms)
);

CREATE TABLE IF NOT EXISTS market_news (
    id               TEXT PRIMARY KEY,
    created_ms       INTEGER,
    stock_id         TEXT,
    price            REAL,
    kind             TEXT,
    lookback_minutes REAL
);
CREATE INDEX IF NOT EXISTS idx_news_stock ON market_news (stock_id, created_ms);

CREATE TABLE IF NOT EXISTS scheduled_news (
    occurrence_id TEXT PRIMARY KEY,
    stock_id      TEXT,
    direction     TEXT,
    target_price  REAL,
    scheduled_ms  INTEGER,
    published_ms  INTEGER
);

-- Results of trade commands sent through the mod's command files.
CREATE TABLE IF NOT EXISTS command_results (
    id          TEXT PRIMARY KEY,
    run         INTEGER,
    action      TEXT,
    stock_id    TEXT,
    percent     REAL,
    status      TEXT,
    reason      TEXT,
    retry_at_ms INTEGER,
    received_ms INTEGER,
    finished_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_cmd_received ON command_results (received_ms);

-- Automation rules (stop-loss, take-profit, ...), see automation.py.
CREATE TABLE IF NOT EXISTS rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id     TEXT    NOT NULL,
    kind         TEXT    NOT NULL,
    side         TEXT    NOT NULL DEFAULT 'long',
    mode         TEXT    NOT NULL DEFAULT 'price',
    value        REAL    NOT NULL,
    percent      INTEGER NOT NULL DEFAULT 100,
    confirm_s    REAL    NOT NULL DEFAULT 0,
    enabled      INTEGER NOT NULL DEFAULT 1,
    extreme      REAL,
    status       TEXT    DEFAULT '',
    created_ms   INTEGER,
    triggered_ms INTEGER,
    repeat       INTEGER NOT NULL DEFAULT 0,
    runs         INTEGER NOT NULL DEFAULT 0,
    activation   REAL                -- trailing buy / short: start following the price only past this level
);

CREATE TABLE IF NOT EXISTS rule_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    time_ms  INTEGER,
    rule_id  INTEGER,
    stock_id TEXT,
    message  TEXT
);

-- Dividend payouts, detected from cash increases at the full minute (the export has no
-- payout data). base = sum(owned * price * dividendRate); factor = amount / base is the
-- dividend multiplier of the player (upgrades/level).
CREATE TABLE IF NOT EXISTS dividends (
    server_ms INTEGER PRIMARY KEY,
    amount    REAL NOT NULL,
    base      REAL,
    factor    REAL
);

-- Progress of the event trader (events.py) per announced event.
CREATE TABLE IF NOT EXISTS event_trades (
    occurrence_id TEXT PRIMARY KEY,
    stock_id      TEXT,
    direction     TEXT,
    phase         TEXT,
    start_price   REAL,
    extreme       REAL,
    info          TEXT,
    updated_ms    INTEGER
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def command_result_key(r) -> str:
    # The game reuses the id per command file ("$PUMP/buypercent") and only counts
    # `run` up; run restarts with the game, so receivedAtMs makes the key unique.
    return f"{r.id or r.action + ':' + r.stock_id}#{r.run}#{r.received_at_ms}"


class Storage:
    def __init__(self, path: Path, shared: bool = False):
        """shared=True allows use from several threads (callers must serialise access with a lock)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path), timeout=10, check_same_thread=not shared)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        # Rows stored by older versions used the bare (reused) id; the game re-exports
        # its last results, so they are simply rebuilt with the unique key.
        self.conn.execute("DELETE FROM command_results WHERE id NOT LIKE '%#%#%'")
        self._migrate()
        self.conn.commit()
        self._pos_cache: Optional[dict] = None
        self._prev_cash: Optional[tuple[int, float]] = None

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created."""
        rule_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(rules)")}
        if "repeat" not in rule_cols:
            self.conn.execute("ALTER TABLE rules ADD COLUMN repeat INTEGER NOT NULL DEFAULT 0")
        if "runs" not in rule_cols:
            self.conn.execute("ALTER TABLE rules ADD COLUMN runs INTEGER NOT NULL DEFAULT 0")
        if "activation" not in rule_cols:
            self.conn.execute("ALTER TABLE rules ADD COLUMN activation REAL")

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ writes

    def store_market(self, snap: MarketSnapshot, include_prices: bool = False) -> bool:
        """Store one market.json snapshot. Returns False if it was already stored."""
        c = self.conn
        p = snap.player
        cur = c.execute(
            """INSERT OR IGNORE INTO snapshots (sequence, written_ms, server_ms, server_tick,
                   market_ready, cash, net_worth, level, ipo_count, next_buy_ms, next_short_ms,
                   buy_cooldown_s, short_cooldown_s, game_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snap.sequence, snap.written_at_ms, snap.server_time_ms, snap.server_tick,
                int(snap.market_ready),
                p.cash if p else None, p.net_worth if p else None,
                p.level if p else None, p.ipo_count if p else None,
                p.next_buy_at_ms if p else None, p.next_short_at_ms if p else None,
                p.buy_cooldown_s if p else None, p.short_cooldown_s if p else None,
                snap.game_version,
            ),
        )
        if cur.rowcount == 0:
            return False

        c.executemany(
            """INSERT INTO stocks (stock_id, name, unlocked, base_price, price_cap, dividend_rate,
                   max_volume, available_shares, last_price, updated_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(stock_id) DO UPDATE SET
                   name=excluded.name, unlocked=excluded.unlocked, base_price=excluded.base_price,
                   price_cap=excluded.price_cap, dividend_rate=excluded.dividend_rate,
                   max_volume=excluded.max_volume, available_shares=excluded.available_shares,
                   last_price=excluded.last_price, updated_ms=excluded.updated_ms""",
            [
                (s.stock_id, s.name, int(s.unlocked), s.base_price, s.price_cap, s.dividend_rate,
                 s.max_volume, s.available_shares, s.price, snap.server_time_ms)
                for s in snap.stocks
            ],
        )

        if include_prices:
            c.executemany(
                "INSERT OR IGNORE INTO prices (stock_id, tick, time_ms, price) VALUES (?,?,?,?)",
                [(s.stock_id, snap.server_tick, snap.server_time_ms, s.price) for s in snap.stocks],
            )

        if p is not None:
            changed = self._store_positions(snap.server_time_ms, p.positions)
            self._detect_dividend(snap, changed)

        c.executemany(
            """INSERT OR IGNORE INTO market_news (id, created_ms, stock_id, price, kind, lookback_minutes)
               VALUES (?,?,?,?,?,?)""",
            [(n.id, n.created_at_ms, n.stock_id, n.price, n.kind, n.lookback_minutes)
             for n in snap.market_news if n.id],
        )
        c.executemany(
            """INSERT OR REPLACE INTO scheduled_news
                   (occurrence_id, stock_id, direction, target_price, scheduled_ms, published_ms)
               VALUES (?,?,?,?,?,?)""",
            [(n.occurrence_id, n.stock_id, n.direction, n.target_price, n.scheduled_at_ms,
              n.published_at_ms) for n in snap.scheduled_news if n.occurrence_id],
        )
        c.executemany(
            """INSERT OR REPLACE INTO command_results
                   (id, run, action, stock_id, percent, status, reason, retry_at_ms, received_ms, finished_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [(command_result_key(r), r.run, r.action, r.stock_id, r.percent, r.status,
              r.reason, r.retry_at_ms, r.received_at_ms, r.finished_at_ms) for r in snap.command_results],
        )
        c.commit()
        return True

    def _store_positions(self, server_ms: int, positions) -> bool:
        """Write changed positions; returns True if anything changed (= a trade happened)."""
        if self._pos_cache is None:
            self._pos_cache = {
                sid: tuple(vals) for sid, *vals in self._latest_positions_rows()
            }
        current = {
            pos.stock_id: (pos.shares_owned, pos.average_buy_price,
                           pos.shares_shorted, pos.average_short_price)
            for pos in positions
        }
        rows = []
        for sid in set(current) | set(self._pos_cache):
            old = self._pos_cache.get(sid)
            # A position missing from the export means it was closed.
            new = current.get(sid, (0.0, 0.0, 0.0, 0.0))
            if old == new or (old is None and not any(new)):
                continue
            rows.append((server_ms, sid, *new))
            self._pos_cache[sid] = new
        if rows:
            self.conn.executemany(
                """INSERT OR REPLACE INTO position_history
                       (server_ms, stock_id, shares_owned, avg_buy_price, shares_shorted, avg_short_price)
                   VALUES (?,?,?,?,?,?)""",
                rows,
            )
        return bool(rows)

    # ------------------------------------------------------------- dividends

    # A payout lands within a few seconds after the full minute (server clock).
    DIVIDEND_WINDOW_MS = 4000
    DIVIDEND_FACTOR_RANGE = (0.2, 50.0)

    def _detect_dividend(self, snap: MarketSnapshot, positions_changed: bool) -> None:
        p = snap.player
        if self._prev_cash is None:
            row = self.conn.execute(
                "SELECT server_ms, cash FROM snapshots WHERE server_ms < ? AND cash IS NOT NULL "
                "ORDER BY server_ms DESC LIMIT 1", (snap.server_time_ms,)).fetchone()
            self._prev_cash = tuple(row) if row else None
        prev, self._prev_cash = self._prev_cash, (snap.server_time_ms, p.cash)
        if prev is None or positions_changed:
            return
        prices = {s.stock_id: (s.price, s.dividend_rate) for s in snap.stocks}
        holdings = {pos.stock_id: pos.shares_owned for pos in p.positions if pos.shares_owned}
        base = sum(n * prices[sid][0] * prices[sid][1] for sid, n in holdings.items() if sid in prices)
        self._record_dividend(prev, snap.server_time_ms, p.cash, base)

    def _record_dividend(self, prev: tuple[int, float], server_ms: int, cash: float, base: float) -> bool:
        delta, gap = cash - prev[1], server_ms - prev[0]
        if delta <= 0 or not 0 < gap < 5000 or base <= 0 or server_ms % 60000 > self.DIVIDEND_WINDOW_MS:
            return False
        factor = delta / base
        lo, hi = self.DIVIDEND_FACTOR_RANGE
        if not lo < factor < hi:
            return False
        self.conn.execute("INSERT OR IGNORE INTO dividends (server_ms, amount, base, factor) VALUES (?,?,?,?)",
                          (server_ms, delta, base, factor))
        return True

    def backfill_dividends(self) -> int:
        """One-time scan of the recorded history for payouts (databases from before this feature)."""
        if self.get_setting("dividends_backfilled") == "1":
            return 0
        rates = dict(self.conn.execute("SELECT stock_id, dividend_rate FROM stocks"))
        hist: dict[str, tuple[list, list]] = {}
        for ts, sid, owned in self.conn.execute(
                "SELECT server_ms, stock_id, shares_owned FROM position_history ORDER BY server_ms"):
            times, values = hist.setdefault(sid, ([], []))
            times.append(ts)
            values.append(owned or 0.0)
        change_times = sorted(t for times, _ in hist.values() for t in times)

        def owned_at(sid: str, ts: int) -> float:
            times, values = hist[sid]
            i = bisect.bisect_right(times, ts) - 1
            return values[i] if i >= 0 else 0.0

        found = 0
        snaps = self.conn.execute(
            "SELECT server_ms, cash FROM snapshots WHERE cash IS NOT NULL ORDER BY server_ms").fetchall()
        for prev, (ts, cash) in zip(snaps, snaps[1:]):
            if cash <= prev[1] or ts % 60000 > self.DIVIDEND_WINDOW_MS:
                continue
            i = bisect.bisect_right(change_times, prev[0])
            if i < len(change_times) and change_times[i] <= ts:
                continue  # a trade happened in between
            base = 0.0
            for sid in hist:
                n = owned_at(sid, prev[0])
                if n and rates.get(sid):
                    price = self.price_at(sid, ts)
                    base += n * (price or 0.0) * rates[sid]
            found += self._record_dividend(prev, ts, cash, base)
        self.conn.commit()
        self.set_setting("dividends_backfilled", "1")
        return found

    def dividend_factor(self, last_n: int = 5) -> tuple[Optional[float], int]:
        """Median multiplier of the most recent payouts and the total number of detected payouts."""
        factors = [r[0] for r in self.conn.execute(
            "SELECT factor FROM dividends ORDER BY server_ms DESC LIMIT ?", (last_n,))]
        count = self.conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0]
        return (statistics.median(factors) if factors else None), count

    def dividends(self, since_ms: int = 0, until_ms: int = 2 ** 62, limit: int = 500) -> list[tuple]:
        """(server_ms, amount, factor), newest first."""
        return self.conn.execute(
            "SELECT server_ms, amount, factor FROM dividends WHERE server_ms BETWEEN ? AND ? "
            "ORDER BY server_ms DESC LIMIT ?", (since_ms, until_ms, limit)).fetchall()

    def dividend_sum(self, since_ms: int, until_ms: int) -> float:
        return self.conn.execute("SELECT COALESCE(SUM(amount), 0) FROM dividends WHERE server_ms BETWEEN ? AND ?",
                                 (since_ms, until_ms)).fetchone()[0]

    def store_prices(self, samples: Iterable[PriceSample]) -> int:
        cur = self.conn.executemany(
            "INSERT OR IGNORE INTO prices (stock_id, tick, time_ms, price) VALUES (?,?,?,?)",
            [(s.stock_id, s.tick, s.time_ms, s.price) for s in samples],
        )
        self.conn.commit()
        return max(cur.rowcount, 0)

    def latest_price_times(self) -> dict[str, int]:
        return dict(self.conn.execute("SELECT stock_id, MAX(time_ms) FROM prices GROUP BY stock_id"))

    # ------------------------------------------------------------------- reads

    def latest_snapshot(self) -> Optional[dict]:
        cur = self.conn.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip([d[0] for d in cur.description], row))

    def stocks(self) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM stocks ORDER BY stock_id")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def stock_ids(self) -> list[str]:
        ids = {r[0] for r in self.conn.execute("SELECT stock_id FROM stocks")}
        ids |= {r[0] for r in self.conn.execute("SELECT DISTINCT stock_id FROM prices")}
        return sorted(ids)

    def latest_time_ms(self) -> Optional[int]:
        return self.conn.execute("SELECT MAX(time_ms) FROM prices").fetchone()[0]

    def first_time_ms(self) -> Optional[int]:
        return self.conn.execute("SELECT MIN(time_ms) FROM prices").fetchone()[0]

    def latest_price(self, stock_id: str) -> Optional[tuple[int, float]]:
        return self.conn.execute(
            "SELECT time_ms, price FROM prices WHERE stock_id=? ORDER BY time_ms DESC LIMIT 1",
            (stock_id,),
        ).fetchone()

    def price_at(self, stock_id: str, time_ms: int) -> Optional[float]:
        """Last known price at or before time_ms."""
        row = self.conn.execute(
            "SELECT price FROM prices WHERE stock_id=? AND time_ms<=? ORDER BY time_ms DESC LIMIT 1",
            (stock_id, time_ms),
        ).fetchone()
        return row[0] if row else None

    def price_series(self, stock_id: str, since_ms: int, until_ms: int,
                     max_points: int = 1200) -> list[tuple[int, float, float, float]]:
        """(time_ms, value, low, high) - downsampled to at most ~max_points buckets."""
        bucket = max(1, (until_ms - since_ms) // max(1, max_points))
        if bucket <= 1000:
            rows = self.conn.execute(
                """SELECT time_ms, price FROM prices
                   WHERE stock_id=? AND time_ms BETWEEN ? AND ? ORDER BY time_ms""",
                (stock_id, since_ms, until_ms),
            ).fetchall()
            return [(t, p, p, p) for t, p in rows]
        return self.conn.execute(
            """SELECT MIN(time_ms), AVG(price), MIN(price), MAX(price) FROM prices
               WHERE stock_id=? AND time_ms BETWEEN ? AND ?
               GROUP BY time_ms / ? ORDER BY 1""",
            (stock_id, since_ms, until_ms, bucket),
        ).fetchall()

    def range_stats(self, stock_id: str, since_ms: int, until_ms: int) -> Optional[tuple]:
        """(min, max, avg, count) over a time range."""
        row = self.conn.execute(
            """SELECT MIN(price), MAX(price), AVG(price), COUNT(*) FROM prices
               WHERE stock_id=? AND time_ms BETWEEN ? AND ?""",
            (stock_id, since_ms, until_ms),
        ).fetchone()
        return row if row and row[3] else None

    def portfolio_series(self, since_ms: int, until_ms: int,
                         max_points: int = 1200) -> list[tuple[int, float, float]]:
        """(server_ms, net_worth, cash) downsampled."""
        bucket = max(1, (until_ms - since_ms) // max(1, max_points))
        return self.conn.execute(
            """SELECT MIN(server_ms), AVG(net_worth), AVG(cash) FROM snapshots
               WHERE server_ms BETWEEN ? AND ? AND net_worth IS NOT NULL
               GROUP BY server_ms / ? ORDER BY 1""",
            (since_ms, until_ms, bucket),
        ).fetchall()

    def snapshot_value_at(self, column: str, server_ms: int) -> Optional[float]:
        assert column in ("net_worth", "cash")
        row = self.conn.execute(
            f"SELECT {column} FROM snapshots WHERE server_ms<=? AND {column} IS NOT NULL "
            "ORDER BY server_ms DESC LIMIT 1",
            (server_ms,),
        ).fetchone()
        return row[0] if row else None

    def _latest_positions_rows(self):
        return self.conn.execute(
            """SELECT stock_id, shares_owned, avg_buy_price, shares_shorted, avg_short_price
               FROM position_history ph
               WHERE server_ms = (SELECT MAX(server_ms) FROM position_history WHERE stock_id=ph.stock_id)"""
        ).fetchall()

    def current_positions(self) -> dict[str, dict]:
        out = {}
        for sid, owned, avg_buy, shorted, avg_short in self._latest_positions_rows():
            if owned or shorted:
                out[sid] = dict(shares_owned=owned or 0.0, avg_buy_price=avg_buy or 0.0,
                                shares_shorted=shorted or 0.0, avg_short_price=avg_short or 0.0)
        return out

    def position_changes(self, limit: int = 200) -> list[tuple]:
        return self.conn.execute(
            """SELECT server_ms, stock_id, shares_owned, avg_buy_price, shares_shorted, avg_short_price
               FROM position_history ORDER BY server_ms DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    def news(self, stock_id: Optional[str] = None, since_ms: int = 0,
             limit: int = 500) -> list[tuple]:
        """(created_ms, stock_id, price, kind, lookback_minutes), newest first."""
        if stock_id:
            return self.conn.execute(
                """SELECT created_ms, stock_id, price, kind, lookback_minutes FROM market_news
                   WHERE stock_id=? AND created_ms>=? ORDER BY created_ms DESC LIMIT ?""",
                (stock_id, since_ms, limit),
            ).fetchall()
        return self.conn.execute(
            """SELECT created_ms, stock_id, price, kind, lookback_minutes FROM market_news
               WHERE created_ms>=? ORDER BY created_ms DESC LIMIT ?""",
            (since_ms, limit),
        ).fetchall()

    def scheduled(self, limit: int = 200) -> list[tuple]:
        """(stock_id, direction, target_price, scheduled_ms, published_ms), newest first."""
        return self.conn.execute(
            """SELECT stock_id, direction, target_price, scheduled_ms, published_ms
               FROM scheduled_news ORDER BY scheduled_ms DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    # ---------------------------------------------------------- event trading

    EVENT_COLUMNS = ("occurrence_id", "stock_id", "direction", "target_price", "scheduled_ms", "published_ms",
                     "phase", "start_price", "extreme", "info")

    def _events(self, where: str, args: tuple, limit: int = 500) -> list[dict]:
        rows = self.conn.execute(
            f"""SELECT s.occurrence_id, s.stock_id, s.direction, s.target_price, s.scheduled_ms, s.published_ms,
                       e.phase, e.start_price, e.extreme, e.info
                FROM scheduled_news s LEFT JOIN event_trades e ON e.occurrence_id = s.occurrence_id
                WHERE {where} ORDER BY s.scheduled_ms LIMIT ?""", (*args, limit)).fetchall()
        return [dict(zip(self.EVENT_COLUMNS, r)) for r in rows]

    def active_events(self, now_ms: int) -> list[dict]:
        """Announced events that are upcoming or happened in the last 15 minutes, with trading state."""
        events = self._events("s.scheduled_ms >= ?", (now_ms - 15 * 60_000,))
        for ev in events:
            if ev["phase"] is None:
                ev["phase"] = "wait_buy" if ev["direction"] == "pump" else "wait_pre"
                self.save_event_state(ev)
        return events

    def recent_events(self, limit: int = 50) -> list[dict]:
        """Newest announced events first (for the UI)."""
        rows = self._events("1", (), limit=10_000)
        return list(reversed(rows))[:limit]

    def save_event_state(self, ev: dict) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO event_trades
                   (occurrence_id, stock_id, direction, phase, start_price, extreme, info, updated_ms)
               VALUES (?,?,?,?,?,?,?,?)""",
            (ev["occurrence_id"], ev["stock_id"], ev["direction"], ev["phase"], ev.get("start_price"),
             ev.get("extreme"), ev.get("info"), int(time.time() * 1000)))
        self.conn.commit()

    def trades(self, stock_id: str, since_ms: int = 0, until_ms: int = 2 ** 62) -> list[dict]:
        """Trades derived from consecutive position changes.

        kind is buy / sell / short / cover. The fill price of opening trades is
        recovered from the change of the average price; closing trades use the
        market price at that moment. Closing trades also carry the average entry
        price before the trade and the realized P/L based on the market price.
        """
        rows = self.conn.execute(
            """SELECT server_ms, shares_owned, avg_buy_price, shares_shorted, avg_short_price
               FROM position_history WHERE stock_id=? AND server_ms <= ? ORDER BY server_ms""",
            (stock_id, until_ms),
        ).fetchall()
        out = []
        # The first row only tells us the state when recording began - not a trade.
        for (_t0, o0, a0, s0, as0), (t, o1, a1, s1, as1) in zip(rows, rows[1:]):
            if t < since_ms:
                continue
            o0, a0, s0, as0, o1, a1, s1, as1 = (v or 0.0 for v in (o0, a0, s0, as0, o1, a1, s1, as1))
            for kind, d, old_n, old_avg, new_n, new_avg in (
                ("buy" if o1 > o0 else "sell", o1 - o0, o0, a0, o1, a1),
                ("short" if s1 > s0 else "cover", s1 - s0, s0, as0, s1, as1),
            ):
                if abs(d) < 1e-9:
                    continue
                market = self.price_at(stock_id, t) or self.price_at(stock_id, t + 5000)
                price = None
                if d > 0 and new_avg:
                    price = (new_avg * new_n - old_avg * old_n) / d
                    # The game's averages are not always consistent; fall back to the market price.
                    if price <= 0 or (market and not 0.5 < price / market < 2):
                        price = None
                if price is None:
                    price = market
                entry = pnl = None
                if d < 0 and price and old_avg:
                    entry = old_avg
                    pnl = (price - old_avg) * abs(d) if kind == "sell" else (old_avg - price) * abs(d)
                out.append(dict(time_ms=t, stock_id=stock_id, kind=kind, shares=abs(d), price=price,
                                entry=entry, pnl=pnl))
        return out

    # ------------------------------------------------------------ statistics

    def bucket_closes(self, stock_id: str, since_ms: int, until_ms: int, bucket_ms: int) -> list[tuple[int, float]]:
        """Last price per time bucket: [(bucket_start_ms, price)], oldest first."""
        # SQLite returns the bare column `price` from the row that matched MAX(time_ms).
        rows = self.conn.execute(
            """SELECT time_ms / ? AS b, price, MAX(time_ms) FROM prices
               WHERE stock_id=? AND time_ms BETWEEN ? AND ? GROUP BY b ORDER BY b""",
            (bucket_ms, stock_id, since_ms, until_ms)).fetchall()
        return [(b * bucket_ms, p) for b, p, _ in rows]

    def base_split(self, stock_id: str, base: float, since_ms: int, until_ms: int) -> tuple[int, int, int]:
        """(samples above base, samples below base, all samples) in the range."""
        row = self.conn.execute(
            """SELECT COALESCE(SUM(price > ?), 0), COALESCE(SUM(price < ?), 0), COUNT(*) FROM prices
               WHERE stock_id=? AND time_ms BETWEEN ? AND ?""",
            (base, base, stock_id, since_ms, until_ms)).fetchone()
        return row[0], row[1], row[2]

    # ------------------------------------------------------------ maintenance

    def compact(self, older_than_ms: int, bucket_ms: int = 10_000) -> tuple[int, int]:
        """Thin out prices and snapshots older than the cutoff to one row per bucket.

        The last real sample of every bucket is kept. Trades, news, dividends,
        rules and logs are never touched. Returns (prices removed, snapshots removed).
        """
        c = self.conn
        doomed, last_key, last_tick = [], None, None
        # rows arrive ordered, so the last row of each (stock, bucket) group is the one to keep
        for sid, tick, ts in c.execute(
                "SELECT stock_id, tick, time_ms FROM prices WHERE time_ms < ? ORDER BY stock_id, time_ms, tick",
                (older_than_ms,)):
            key = (sid, ts // bucket_ms)
            if key == last_key:
                doomed.append((sid, last_tick))
            last_key, last_tick = key, tick
        c.executemany("DELETE FROM prices WHERE stock_id=? AND tick=?", doomed)

        doomed_snaps, last_bucket, last_id = [], None, None
        for sid_, ts in c.execute("SELECT id, server_ms FROM snapshots WHERE server_ms < ? ORDER BY server_ms, id",
                                  (older_than_ms,)):
            bucket = ts // bucket_ms
            if bucket == last_bucket:
                doomed_snaps.append((last_id,))
            last_bucket, last_id = bucket, sid_
        c.executemany("DELETE FROM snapshots WHERE id=?", doomed_snaps)
        c.commit()
        return len(doomed), len(doomed_snaps)

    def vacuum(self) -> None:
        """Give freed pages back to the file system (needs a moment on large files)."""
        self.conn.execute("VACUUM")
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def db_info(self) -> dict:
        size = sum(os.path.getsize(f) for f in (self.path, Path(f"{self.path}-wal"))
                   if os.path.exists(f))
        oldest = self.conn.execute("SELECT MIN(time_ms) FROM prices").fetchone()[0]
        return dict(size=size, oldest_ms=oldest, **self.counts())

    # ------------------------------------------------------------ automation

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
        self.conn.commit()

    def rules(self, enabled_only: bool = False) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM rules" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY id")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def add_rule(self, stock_id: str, kind: str, side: str, mode: str, value: float,
                 percent: int, confirm_s: float, created_ms: int, repeat: bool = False,
                 status: str = "", activation: Optional[float] = None) -> int:
        cur = self.conn.execute(
            """INSERT INTO rules (stock_id, kind, side, mode, value, percent, confirm_s, enabled, status,
                                   created_ms, repeat, activation)
               VALUES (?,?,?,?,?,?,?,1,?,?,?,?)""",
            (stock_id, kind, side, mode, value, percent, confirm_s, status, created_ms, int(repeat), activation))
        self.conn.commit()
        return cur.lastrowid

    def update_rule(self, rule_id: int, **fields) -> None:
        allowed = {"enabled", "extreme", "status", "triggered_ms", "repeat", "runs",
                   "stock_id", "kind", "side", "mode", "value", "percent", "confirm_s", "activation"}
        assert set(fields) <= allowed, fields
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE rules SET {sets} WHERE id=?", (*fields.values(), rule_id))
        self.conn.commit()

    def delete_rule(self, rule_id: int) -> None:
        self.conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        self.conn.commit()

    def log_rule(self, time_ms: int, rule_id: Optional[int], stock_id: str, message: str) -> None:
        self.conn.execute("INSERT INTO rule_log (time_ms, rule_id, stock_id, message) VALUES (?,?,?,?)",
                          (time_ms, rule_id, stock_id, message))
        self.conn.commit()

    def rule_log(self, limit: int = 200) -> list[tuple]:
        return self.conn.execute(
            "SELECT id, time_ms, rule_id, stock_id, message FROM rule_log ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()

    def command_results(self, limit: int = 100) -> list[dict]:
        cur = self.conn.execute(
            """SELECT id, run, action, stock_id, percent, status, reason, retry_at_ms, received_ms, finished_ms
               FROM command_results ORDER BY received_ms DESC, run DESC LIMIT ?""",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def counts(self) -> dict[str, int]:
        q = lambda t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
        return {"prices": q("prices"), "snapshots": q("snapshots"), "news": q("market_news")}

    # ------------------------------------------------------------------ export

    def export_prices_csv(self, path: Path, since_ms: int, until_ms: int,
                          stock_ids: Optional[list[str]] = None) -> int:
        sql = "SELECT time_ms, stock_id, tick, price FROM prices WHERE time_ms BETWEEN ? AND ?"
        args: list = [since_ms, until_ms]
        if stock_ids:
            sql += f" AND stock_id IN ({','.join('?' * len(stock_ids))})"
            args += stock_ids
        sql += " ORDER BY time_ms, stock_id"
        n = 0
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["time", "time_ms", "stock_id", "tick", "price"])
            for t, sid, tick, price in self.conn.execute(sql, args):
                w.writerow([datetime.fromtimestamp(t / 1000).isoformat(sep=" ", timespec="milliseconds"),
                            t, sid, tick, f"{price:.6f}"])
                n += 1
        return n
