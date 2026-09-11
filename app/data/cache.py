from __future__ import annotations

from datetime import datetime

from app.data.freshness import validate_live_price
from app.data.market_data import Candle, LivePrice, StaleMarketDataError


class MarketDataCache:
    """In-memory hot cache for live prices and recent candles."""

    def __init__(self, *, max_candles_per_series: int = 1000) -> None:
        if max_candles_per_series <= 0:
            raise ValueError("max_candles_per_series must be positive")
        self.max_candles_per_series = max_candles_per_series
        self._live: dict[str, LivePrice] = {}
        self._candles: dict[tuple[str, str], list[Candle]] = {}

    def put_live_price(self, price: LivePrice) -> None:
        self._live[price.symbol.upper()] = price

    def get_live_price(
        self,
        symbol: str,
        *,
        max_age_seconds: int | None = None,
        now: datetime | None = None,
    ) -> LivePrice | None:
        price = self._live.get(symbol.upper())
        if price is None:
            return None
        if max_age_seconds is None:
            return price
        try:
            return validate_live_price(price, max_age_seconds, now=now)
        except StaleMarketDataError:
            return None

    def put_candles(self, candles: list[Candle] | tuple[Candle, ...]) -> None:
        for candle in candles:
            key = (candle.symbol.upper(), candle.timeframe)
            series = self._candles.setdefault(key, [])
            by_timestamp = {item.timestamp: item for item in series}
            by_timestamp[candle.timestamp] = candle
            ordered = sorted(by_timestamp.values(), key=lambda item: item.timestamp)
            self._candles[key] = ordered[-self.max_candles_per_series :]

    def get_candles(self, symbol: str, timeframe: str, *, limit: int = 200) -> list[Candle]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        series = self._candles.get((symbol.upper(), timeframe), [])
        return list(series[-limit:])

    def clear(self) -> None:
        self._live.clear()
        self._candles.clear()
