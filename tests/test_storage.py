"""Storage of market snapshots (screenstocks/storage.py)."""

import sqlite3

from screenstocks.reader import parse_market
from screenstocks.storage import SCHEMA_VERSION, Storage


def test_database_of_2_1_3_gets_the_rule_columns(tmp_path):
    """A 2.1.x database (user_version 1, rules without the round columns) is migrated on open: 2.2.0 to 2.3.2 never
    added them, so saving a repeating rule failed with "no such column: pause_until_ms"."""
    path = tmp_path / "old.db"
    Storage(path).close()
    old = sqlite3.connect(path)
    for col in ("repeat_times", "repeat_wait_s", "pause_until_ms"):
        old.execute(f"ALTER TABLE rules DROP COLUMN {col}")
    old.execute("PRAGMA user_version = 1")
    old.commit()
    old.close()
    db = Storage(path)
    try:
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        rid = db.add_rule("$PUMP", "buy_limit", "long", "price", 5.0, 100, 0, 1_000, repeat=True,
                          repeat_times=3, repeat_wait_s=60.0)
        db.update_rule(rid, runs=3, extreme=None, pause_until_ms=123)
        rule = next(r for r in db.rules() if r["id"] == rid)
        assert (rule["repeat_times"], rule["repeat_wait_s"], rule["pause_until_ms"]) == (3, 60.0, 123)
    finally:
        db.close()


def test_share_counts_beyond_64_bit_integers(tmp_path):
    """Late in the game maxVolume / availableShares outgrow SQLite's 64-bit integers (OverflowError before)."""
    huge = 3 * 10 ** 19
    snap = parse_market({
        "sequence": 1, "serverTimeMs": 1_000, "serverTick": 1, "marketReady": True,
        "stocks": [{"stockId": "$PUMP", "name": "Pump", "price": 12.5, "unlocked": True,
                    "maxVolume": huge, "availableShares": str(huge)}],
    })
    db = Storage(tmp_path / "test.db")
    try:
        assert db.store_market(snap, include_prices=True)
        stock = next(s for s in db.stocks() if s["stock_id"] == "$PUMP")
        assert stock["available_shares"] == float(huge) and stock["max_volume"] == float(huge)
    finally:
        db.close()


def _ipo_snapshot(ts, count, owned, cash):
    player = {"cash": cash, "netWorth": cash + owned * 20,
              "positions": [{"stockId": "$PUMP", "sharesOwned": owned, "averageBuyPrice": 10}]}
    if count is not None:
        player["ipoCount"] = count
    return parse_market({
        "sequence": ts, "writtenAtMs": ts, "serverTimeMs": ts, "serverTick": ts,
        "marketReady": True, "player": player,
        "stocks": [{"stockId": "$PUMP", "price": 20}],
    })


def test_ipo_history_and_all_time_on_migrated_database(tmp_path):
    from threading import Lock

    from screenstocks.web.portfolio_api import PortfolioApi

    path = tmp_path / "history.db"
    db = Storage(path)
    for row in [(1000, 0, 10, 200), (2000, 0, 8, 240), (3000, 2, 0, 100),
                (4000, None, 3, 70), (5000, 1, 2, 90), (6000, 2, 1, 110)]:
        assert db.store_market(_ipo_snapshot(*row), include_prices=True)
    assert db.ipo_runs() == [2, 0]  # no invented IPO 1, missing data and lower counts are ignored
    db.conn.executemany("INSERT INTO dividends VALUES (?, ?, ?, ?)", [(2000, 5, 5, 1), (5000, 9, 9, 1)])
    db.conn.execute("DROP TABLE ipo_runs")
    db.conn.execute("PRAGMA user_version = 2")
    db.conn.commit()
    db.close()

    db = Storage(path)
    try:
        api = PortfolioApi()
        api._db, api._lock, api._closing = db, Lock(), False
        assert db.ipo_runs() == [2, 0]
        assert api.portfolio("all", 0)["cash"] == 240
        assert api.portfolio("all", 0)["positions"][0]["owned"] == 8
        assert api.portfolio("all", 0)["received"] == 5
        assert api.portfolio("all", "current")["cash"] == 110
        assert api.portfolio("all")["received"] == 14
        assert len(api.portfolio_chart("all", 0)["cash"]) == 2
        assert len(api.portfolio_chart("all", 2)["cash"]) == 4
        old, current, all_time = api.journal("all", 0), api.journal("all", 2), api.journal("all")
        assert [x["time"] for x in old["trades"]] == [2000]
        assert [x["time"] for x in current["trades"]] == [4000, 5000, 6000]
        assert all_time["realized"] == old["realized"] + current["realized"] == 40
        assert all_time["dividends"] == 14
        db.compact(10_000)
        assert db.ipo_runs() == [2, 0]
        assert db.snapshot_value_at("cash", 3000, since_ms=3000) == 100
    finally:
        db.close()
