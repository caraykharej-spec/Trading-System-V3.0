from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable, Protocol

from app.data.market_data import Candle


@dataclass(frozen=True)
class TradeEvent:
    provider: str
    symbol: str
    event_id: str
    sequence: int
    price: Decimal
    quantity: Decimal
    timestamp: datetime

    def validate(self) -> None:
        if not self.provider or not self.symbol or not self.event_id:
            raise ValueError("trade event identifiers cannot be empty")
        if self.sequence < 0:
            raise ValueError("trade event sequence cannot be negative")
        if self.price <= 0:
            raise ValueError("trade event price must be positive")
        if self.quantity < 0:
            raise ValueError("trade event quantity cannot be negative")
        if self.timestamp.tzinfo is None:
            raise ValueError("trade event timestamp must be timezone-aware")


@dataclass(frozen=True)
class CandleStreamEvent:
    provider: str
    event_id: str
    sequence: int
    candle: Candle
    received_at: datetime
    server_time_ms: int | None = None

    def validate(self) -> None:
        if not self.provider or not self.event_id:
            raise ValueError("candle event identifiers cannot be empty")
        if self.sequence < 0:
            raise ValueError("candle event sequence cannot be negative")
        if self.received_at.tzinfo is None:
            raise ValueError("candle event received_at must be timezone-aware")
        if self.candle.timestamp.tzinfo is None:
            raise ValueError("candle timestamp must be timezone-aware")
        if self.candle.open <= 0 or self.candle.high <= 0:
            raise ValueError("candle prices must be positive")
        if self.candle.low <= 0 or self.candle.close <= 0:
            raise ValueError("candle prices must be positive")
        if self.candle.low > self.candle.high:
            raise ValueError("candle low cannot exceed high")
        if self.candle.volume < 0:
            raise ValueError("candle volume cannot be negative")
        if self.server_time_ms is not None and self.server_time_ms <= 0:
            raise ValueError("server_time_ms must be positive when provided")


class MarketDataStreamSource(Protocol):
    @property
    def name(self) -> str: ...

    def start(self, handler: Callable[[TradeEvent], None]) -> None: ...

    def stop(self) -> None: ...


class CandleMarketDataStreamSource(Protocol):
    @property
    def name(self) -> str: ...

    def start(self, handler: Callable[[CandleStreamEvent], None]) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class IngestSnapshot:
    accepted: int
    duplicates: int
    out_of_order: int
    invalid: int


class MarketDataStreamIngestor:
    """Normalize trade-stream delivery with duplicate and sequence protection."""

    def __init__(self, handler: Callable[[TradeEvent], None]) -> None:
        self._handler = handler
        self._seen_event_ids: set[tuple[str, str]] = set()
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._accepted = 0
        self._duplicates = 0
        self._out_of_order = 0
        self._invalid = 0

    def ingest(self, event: TradeEvent) -> bool:
        try:
            event.validate()
        except ValueError:
            self._invalid += 1
            return False

        event_key = (event.provider.lower(), event.event_id)
        if event_key in self._seen_event_ids:
            self._duplicates += 1
            return False

        sequence_key = (event.provider.lower(), event.symbol.upper())
        previous = self._last_sequence.get(sequence_key)
        if previous is not None and event.sequence <= previous:
            self._out_of_order += 1
            return False

        self._handler(event)
        self._seen_event_ids.add(event_key)
        self._last_sequence[sequence_key] = event.sequence
        self._accepted += 1
        return True

    def snapshot(self) -> IngestSnapshot:
        return IngestSnapshot(
            accepted=self._accepted,
            duplicates=self._duplicates,
            out_of_order=self._out_of_order,
            invalid=self._invalid,
        )


class CandleStreamIngestor:
    """Protect direct OHLCV streams from duplicates and out-of-order delivery."""

    def __init__(self, handler: Callable[[CandleStreamEvent], None]) -> None:
        self._handler = handler
        self._seen_event_ids: set[tuple[str, str]] = set()
        self._last_sequence: dict[tuple[str, str, str], int] = {}
        self._accepted = 0
        self._duplicates = 0
        self._out_of_order = 0
        self._invalid = 0

    def ingest(self, event: CandleStreamEvent) -> bool:
        try:
            event.validate()
        except ValueError:
            self._invalid += 1
            return False

        event_key = (event.provider.lower(), event.event_id)
        if event_key in self._seen_event_ids:
            self._duplicates += 1
            return False

        sequence_key = (
            event.provider.lower(),
            event.candle.symbol.upper(),
            event.candle.timeframe,
        )
        previous = self._last_sequence.get(sequence_key)
        if previous is not None and event.sequence <= previous:
            self._out_of_order += 1
            return False

        self._handler(event)
        self._seen_event_ids.add(event_key)
        self._last_sequence[sequence_key] = event.sequence
        self._accepted += 1
        return True

    def snapshot(self) -> IngestSnapshot:
        return IngestSnapshot(
            accepted=self._accepted,
            duplicates=self._duplicates,
            out_of_order=self._out_of_order,
            invalid=self._invalid,
        )
