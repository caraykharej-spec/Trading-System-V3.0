from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class LivePrice:
    symbol: str
    price: Decimal
    as_of: datetime
    provider: str


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class MarketDataRequest:
    symbol: str
    timeframe: str | None = None
    limit: int = 200


class MarketDataError(RuntimeError):
    """Base error for market-data provider failures."""


class StaleMarketDataError(MarketDataError):
    """Raised when data is too old to be considered live/usable."""
