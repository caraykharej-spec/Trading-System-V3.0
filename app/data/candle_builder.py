from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.data.market_data import Candle
from app.data.streaming import TradeEvent


def timeframe_seconds(timeframe: str) -> int:
    if len(timeframe) < 2:
        raise ValueError(f"invalid timeframe: {timeframe}")
    unit = timeframe[-1].lower()
    try:
        value = int(timeframe[:-1])
    except ValueError as exc:
        raise ValueError(f"invalid timeframe: {timeframe}") from exc
    if value <= 0:
        raise ValueError("timeframe value must be positive")
    multiplier = {"m": 60, "h": 3600, "d": 86400}.get(unit)
    if multiplier is None:
        raise ValueError(f"unsupported timeframe unit: {unit}")
    return value * multiplier


def _bucket_start(timestamp: datetime, seconds: int) -> datetime:
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    epoch = int(timestamp.timestamp())
    bucket = epoch - (epoch % seconds)
    return datetime.fromtimestamp(bucket, tz=timezone.utc)


class CandleBuilder:
    """Aggregate validated trade events into deterministic OHLCV candles."""

    def __init__(self, timeframe: str) -> None:
        self.timeframe = timeframe
        self._seconds = timeframe_seconds(timeframe)
        self._current: dict[str, Candle] = {}

    def add_trade(self, event: TradeEvent) -> Candle | None:
        event.validate()
        symbol = event.symbol.upper()
        bucket = _bucket_start(event.timestamp, self._seconds)
        current = self._current.get(symbol)

        if current is None:
            self._current[symbol] = self._new_candle(symbol, bucket, event)
            return None

        if bucket < current.timestamp:
            raise ValueError("trade event belongs to an already closed candle")

        if bucket == current.timestamp:
            self._current[symbol] = Candle(
                symbol=symbol,
                timeframe=self.timeframe,
                timestamp=current.timestamp,
                open=current.open,
                high=max(current.high, event.price),
                low=min(current.low, event.price),
                close=event.price,
                volume=current.volume + event.quantity,
            )
            return None

        closed = current
        self._current[symbol] = self._new_candle(symbol, bucket, event)
        return closed

    def current(self, symbol: str) -> Candle | None:
        return self._current.get(symbol.upper())

    def flush(self, symbol: str) -> Candle | None:
        return self._current.pop(symbol.upper(), None)

    def _new_candle(self, symbol: str, bucket: datetime, event: TradeEvent) -> Candle:
        price: Decimal = event.price
        return Candle(
            symbol=symbol,
            timeframe=self.timeframe,
            timestamp=bucket,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=event.quantity,
        )
