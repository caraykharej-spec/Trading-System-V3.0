from __future__ import annotations

from dataclasses import dataclass

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.provider_router import MarketProvider
from app.universe.symbol_mapping import SymbolMapper


@dataclass(frozen=True)
class MappedMarketProvider:
    """Translate canonical symbols at the provider boundary and normalize results back."""

    provider: MarketProvider
    mapper: SymbolMapper

    @property
    def name(self) -> str:
        return self.provider.name

    def get_live_price(self, symbol: str) -> LivePrice:
        provider_symbol = self.mapper.to_provider(symbol, self.name)
        raw = self.provider.get_live_price(provider_symbol)
        return LivePrice(
            symbol=symbol,
            price=raw.price,
            as_of=raw.as_of,
            provider=raw.provider,
        )

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        provider_symbol = self.mapper.to_provider(request.symbol, self.name)
        raw = self.provider.get_candles(
            MarketDataRequest(
                symbol=provider_symbol,
                timeframe=request.timeframe,
                limit=request.limit,
            )
        )
        return [
            Candle(
                symbol=request.symbol,
                timeframe=candle.timeframe,
                timestamp=candle.timestamp,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            )
            for candle in raw
        ]
