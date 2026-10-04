"""Background thread that watches the export files and records them into SQLite."""

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config
from .reader import parse_history, parse_market, read_json
from .storage import Storage

log = logging.getLogger(__name__)


@dataclass
class CollectorStatus:
    running: bool = False
    market_found: bool = False
    history_found: bool = False
    last_market_read: float = 0.0     # local time.time()
    last_history_read: float = 0.0
    snapshots_stored: int = 0
    samples_stored: int = 0
    read_errors: int = 0
    last_error: str = ""
    game_version: str = ""
    format_version: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def copy(self) -> "CollectorStatus":
        with self.lock:
            return CollectorStatus(**{k: v for k, v in self.__dict__.items() if k != "lock"})


def _file_signature(path: Path) -> Optional[tuple[int, int]]:
    try:
        st = path.stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


class Collector(threading.Thread):
    def __init__(self, export_dir: Path, db_path: Path, poll_interval_s: float = config.POLL_INTERVAL_S):
        super().__init__(name="collector", daemon=True)
        self.export_dir = Path(export_dir)
        self.db_path = Path(db_path)
        self.poll_interval_s = poll_interval_s
        self.status = CollectorStatus()
        self._stop_event = threading.Event()
        self._market_sig = None
        self._history_sig = None
        self._last_price_time: dict[str, int] = {}

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        storage = Storage(self.db_path)
        self._last_price_time = storage.latest_price_times()
        try:
            n = storage.backfill_dividends()
            if n:
                log.info("detected %d dividend payouts in the existing history", n)
        except Exception:
            log.exception("dividend backfill failed")
        try:
            cutoff = int((time.time() - config.RETENTION_DAYS * 86400) * 1000)
            removed = storage.compact(cutoff, config.COMPACT_BUCKET_MS)
            if any(removed):
                log.info("compacted history older than %d days: %d prices, %d snapshots removed",
                         config.RETENTION_DAYS, *removed)
        except Exception:
            log.exception("compaction failed")
        with self.status.lock:
            self.status.running = True
        try:
            while not self._stop_event.is_set():
                try:
                    self._poll(storage)
                except Exception as exc:  # keep recording no matter what
                    log.exception("collector error")
                    self._error(f"{type(exc).__name__}: {exc}")
                self._stop_event.wait(self.poll_interval_s)
        finally:
            storage.close()
            with self.status.lock:
                self.status.running = False

    def _error(self, msg: str) -> None:
        with self.status.lock:
            self.status.read_errors += 1
            self.status.last_error = msg

    def _poll(self, storage: Storage) -> None:
        market_path = self.export_dir / config.MARKET_FILE
        history_path = self.export_dir / config.HISTORY_FILE

        history_sig = _file_signature(history_path)
        market_sig = _file_signature(market_path)
        with self.status.lock:
            self.status.history_found = history_sig is not None
            self.status.market_found = market_sig is not None

        # History first: it carries the full per-second price series.
        if history_sig is not None and history_sig != self._history_sig:
            data = read_json(history_path)
            if data is None:
                self._error("history.json konnte nicht gelesen werden (wird gerade geschrieben?)")
            else:
                self._history_sig = history_sig
                fresh = [s for s in parse_history(data)
                         if s.time_ms > self._last_price_time.get(s.stock_id, 0)]
                n = storage.store_prices(fresh) if fresh else 0
                for s in fresh:
                    if s.time_ms > self._last_price_time.get(s.stock_id, 0):
                        self._last_price_time[s.stock_id] = s.time_ms
                with self.status.lock:
                    self.status.samples_stored += n
                    self.status.last_history_read = time.time()

        if market_sig is not None and market_sig != self._market_sig:
            data = read_json(market_path)
            if data is None:
                self._error("market.json konnte nicht gelesen werden (wird gerade geschrieben?)")
                return
            self._market_sig = market_sig
            snap = parse_market(data)
            # Without history.json the market snapshot is the only price source.
            stored = storage.store_market(snap, include_prices=history_sig is None)
            with self.status.lock:
                self.status.last_market_read = time.time()
                self.status.game_version = snap.game_version
                self.status.format_version = snap.format_version
                if stored:
                    self.status.snapshots_stored += 1
