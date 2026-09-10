from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from app.data.market_data import Candle, LivePrice, MarketDataRequest


class MarketDataProvider(ABC):
    """Stable contract for public market-data adapters.

    V3 market-data providers are intentionally no-key. Authentication and
    execution credentials are outside this read-only data boundary.
    """

    name: str
    requires_credentials: ClassVar[bool] = False

    @abstractmethod
    def get_live_price(self, symbol: str) -> LivePrice:
        raise NotImplementedError

    @abstractmethod
    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        raise NotImplementedError


def require_public_no_key(provider: MarketDataProvider) -> MarketDataProvider:
    """Reject credentialed providers at the current V3 public-data boundary."""
    if provider.requires_credentials:
        raise ValueError(f"credentialed market-data provider is not allowed: {provider.name}")
    return provider
