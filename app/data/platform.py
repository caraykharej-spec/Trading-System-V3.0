from __future__ import annotations

from datetime import datetime

from app.data.cache import MarketDataCache
from app.data.candle_builder import CandleBuilder
from app.data.historical_store import CandleHistoryStore
from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.provider_router import ProviderRouter
from app.data.streaming import CandleStreamEvent, TradeEvent


class ProductionMarketDataPlatform:
    """Unify hot cache, provider failover, stream ingestion, and durable OHLC history."""

    def __init__(
        self,
        *,
        router: ProviderRouter,
        cache: MarketDataCache,
        history: CandleHistoryStore,
        timeframes: tuple[str, ...] = ("15m", "1h", "4h"),
    ) -> None:
        if not timeframes:
            raise ValueError("at least one candle timeframe is required")
        self.router = router
        self.cache = cache
        self.history = history
        self.builders = {timeframe: CandleBuilder(timeframe) for timeframe in timeframes}

    def get_live_price(
        self,
        symbol: str,
        *,
        max_age_seconds: int = 30,
        now: datetime | None = None,
    ) -> LivePrice:
        cached = self.cache.get_live_price(
            symbol,
            max_age_seconds=max_age_seconds,
            now=now,
        )
        if cached is not None:
            return cached
        price = self.router.get_live_price(symbol, now=now)
        self.cache.put_live_price(price)
        return price

    def get_candles(
        self,
        request: MarketDataRequest,
        *,
        max_age_seconds: int | None = None,
        now: datetime | None = None,
    ) -> list[Candle]:
        if request.timeframe is None:
            raise ValueError("timeframe is required for candle retrieval")

        cached = self.cache.get_candles(
            request.symbol,
            request.timeframe,
            limit=request.limit,
        )
        if len(cached) >= request.limit:
            return cached[-request.limit :]

        stored = self.history.load(
            request.symbol,
            request.timeframe,
            limit=request.limit,
        )
        if len(stored) >= request.limit:
            self.cache.put_candles(stored)
            return stored[-request.limit :]

        candles = self.router.get_candles(
            request,
            max_age_seconds=max_age_seconds,
            now=now,
        )
        self.cache.put_candles(candles)
        self.history.upsert(candles)
        return candles

    def ingest_trade(self, event: TradeEvent) -> tuple[Candle, ...]:
        event.validate()
        self.cache.put_live_price(
            LivePrice(
                symbol=event.symbol.upper(),
                price=event.price,
                as_of=event.timestamp,
                provider=event.provider,
            )
        )

        closed: list[Candle] = []
        for builder in self.builders.values():
            candle = builder.add_trade(event)
            if candle is not None:
                closed.append(candle)

        if closed:
            self.cache.put_candles(closed)
            self.history.upsert(closed)
        return tuple(closed)

    def ingest_candle(self, event: CandleStreamEvent) -> Candle:
        """Persist a normalized provider candle update idempotently."""

        event.validate()
        candle = event.candle
        self.cache.put_candles((candle,))
        self.history.upsert((candle,))
        return candle

    def flush_open_candles(self, symbol: str) -> tuple[Candle, ...]:
        candles = tuple(
            candle
            for builder in self.builders.values()
            if (candle := builder.flush(symbol)) is not None
        )
        if candles:
            self.cache.put_candles(candles)
            self.history.upsert(candles)
        return candles
