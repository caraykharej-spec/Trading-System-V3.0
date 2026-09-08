from __future__ import annotations

from abc import ABC, abstractmethod

from app.data.market_data import Candle, LivePrice, MarketDataRequest


class MarketDataProvider(ABC):
    """Stable interface implemented by Storm, Gate.io and Yahoo adapters."""

    name: str

    @abstractmethod
    def get_live_price(self, symbol: str) -> LivePrice:
        raise NotImplementedError

    @abstractmethod
    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        raise NotImplementedError
