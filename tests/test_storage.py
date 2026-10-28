"""Storage of market snapshots (screenstocks/storage.py)."""

from screenstocks.reader import parse_market
from screenstocks.storage import Storage


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
