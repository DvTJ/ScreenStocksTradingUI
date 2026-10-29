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
