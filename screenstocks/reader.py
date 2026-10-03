"""Reading and parsing of the Screen Stocks mod export files."""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def _float(value: Any, default: float = 0.0) -> float:
    """The game writes large numbers as strings ("785149232.21"), small ones as numbers."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(_float(value, default))


@dataclass
class Stock:
    stock_id: str
    name: str
    price: float
    unlocked: bool
    base_price: float
    price_cap: float
    dividend_rate: float
    max_volume: int
    available_shares: int


@dataclass
class Position:
    stock_id: str
    shares_owned: float
    average_buy_price: float
    shares_shorted: float
    average_short_price: float


@dataclass
class Player:
    cash: float
    net_worth: float
    level: int
    ipo_count: int
    next_buy_at_ms: int
    next_short_at_ms: int
    buy_cooldown_s: float
    short_cooldown_s: float
    positions: list[Position] = field(default_factory=list)


@dataclass
class NewsItem:
    id: str
    created_at_ms: int
    stock_id: str
    price: float
    kind: str
    lookback_minutes: float


@dataclass
class ScheduledNews:
    occurrence_id: str
    stock_id: str
    direction: str
    target_price: float
    scheduled_at_ms: int
    published_at_ms: int


@dataclass
class CommandResult:
    id: str
    run: int
    action: str
    stock_id: str
    percent: float
    status: str
    reason: str
    retry_at_ms: int
    received_at_ms: int
    finished_at_ms: int


@dataclass
class MarketSnapshot:
    format_version: int
    game_version: str
    sequence: int
    written_at_ms: int
    server_time_ms: int
    server_tick: int
    last_price_update_at_ms: int
    market_ready: bool
    stocks: list[Stock]
    player: Optional[Player]
    market_news: list[NewsItem]
    scheduled_news: list[ScheduledNews]
    command_results: list[CommandResult] = field(default_factory=list)


@dataclass
class PriceSample:
    stock_id: str
    tick: int
    time_ms: int
    price: float


def read_json(path: Path, retries: int = 5, delay_s: float = 0.05) -> Optional[dict]:
    """Read a JSON file that the game may be rewriting at the same moment.

    A half-written or locked file raises; we retry a few times and give up
    with None so the caller can try again on the next poll.
    """
    for attempt in range(retries):
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, UnicodeDecodeError, PermissionError, OSError):
            pass
        if attempt < retries - 1:
            time.sleep(delay_s)
    return None


def parse_market(d: dict) -> MarketSnapshot:
    stocks = [
        Stock(
            stock_id=s.get("stockId", "?"),
            name=s.get("name") or s.get("stockId", "?"),
            price=_float(s.get("price")),
            unlocked=bool(s.get("unlocked", False)),
            base_price=_float(s.get("basePrice")),
            price_cap=_float(s.get("priceCap")),
            dividend_rate=_float(s.get("dividendRate")),
            max_volume=_int(s.get("maxVolume")),
            available_shares=_int(s.get("availableShares")),
        )
        for s in d.get("stocks") or []
    ]

    player = None
    p = d.get("player")
    if isinstance(p, dict):
        player = Player(
            cash=_float(p.get("cash")),
            net_worth=_float(p.get("netWorth")),
            level=_int(p.get("level")),
            ipo_count=_int(p.get("ipoCount")),
            next_buy_at_ms=_int(p.get("nextBuyAtMs")),
            next_short_at_ms=_int(p.get("nextShortAtMs")),
            buy_cooldown_s=_float(p.get("buyCooldownSeconds")),
            short_cooldown_s=_float(p.get("shortCooldownSeconds")),
            positions=[
                Position(
                    stock_id=pos.get("stockId", "?"),
                    shares_owned=_float(pos.get("sharesOwned")),
                    average_buy_price=_float(pos.get("averageBuyPrice")),
                    shares_shorted=_float(pos.get("sharesShorted")),
                    average_short_price=_float(pos.get("averageShortPrice")),
                )
                for pos in p.get("positions") or []
            ],
        )

    news = [
        NewsItem(
            id=n.get("id", ""),
            created_at_ms=_int(n.get("createdAtMs")),
            stock_id=n.get("stockId", "?"),
            price=_float(n.get("price")),
            kind=n.get("kind", ""),
            lookback_minutes=_float(n.get("lookbackMinutes")),
        )
        for n in d.get("marketNews") or []
    ]

    scheduled = [
        ScheduledNews(
            occurrence_id=n.get("occurrenceId", ""),
            stock_id=n.get("stockId", "?"),
            direction=n.get("direction", ""),
            target_price=_float(n.get("targetPrice")),
            scheduled_at_ms=_int(n.get("scheduledAtMs")),
            published_at_ms=_int(n.get("publishedAtMs")),
        )
        for n in d.get("scheduledNews") or []
    ]

    results = [
        CommandResult(
            id=str(r.get("id") or ""),
            run=_int(r.get("run")),
            action=r.get("action") or "",
            stock_id=r.get("stockId") or "",
            percent=_float(r.get("percent")),
            status=r.get("status") or "",
            reason=r.get("reason") or "",
            retry_at_ms=_int(r.get("retryAtMs")),
            received_at_ms=_int(r.get("receivedAtMs")),
            finished_at_ms=_int(r.get("finishedAtMs")),
        )
        for r in d.get("commandResults") or []
        if isinstance(r, dict)
    ]

    return MarketSnapshot(
        format_version=_int(d.get("formatVersion")),
        game_version=str(d.get("gameVersion", "")),
        sequence=_int(d.get("sequence")),
        written_at_ms=_int(d.get("writtenAtMs")),
        server_time_ms=_int(d.get("serverTimeMs")),
        server_tick=_int(d.get("serverTick")),
        last_price_update_at_ms=_int(d.get("lastPriceUpdateAtMs")),
        market_ready=bool(d.get("marketReady", False)),
        stocks=stocks,
        player=player,
        market_news=news,
        scheduled_news=scheduled,
        command_results=results,
    )


def parse_history(d: dict) -> list[PriceSample]:
    samples = []
    for s in d.get("stocks") or []:
        sid = s.get("stockId", "?")
        for smp in s.get("samples") or []:
            samples.append(
                PriceSample(
                    stock_id=sid,
                    tick=_int(smp.get("tick")),
                    time_ms=_int(smp.get("timeMs")),
                    price=_float(smp.get("price")),
                )
            )
    return samples
