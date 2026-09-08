from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.data.market_data import Candle, LivePrice
from app.data.providers.http import ProviderError


class MarketProvider(Protocol):
    name: str

    def get_live_price(self, symbol: str) -> LivePrice: ...


@dataclass(frozen=True)
class ProviderRouter:
    providers: tuple[MarketProvider, ...]

    def get_live_price(self, symbol: str) -> LivePrice:
        errors: list[str] = []
        for provider in self.providers:
            try:
                result = provider.get_live_price(symbol)
                if result.price <= 0:
                    raise ProviderError("non-positive price")
                return result
            except Exception as exc:
                errors.append(f"{getattr(provider, 'name', provider.__class__.__name__)}: {exc}")
        raise ProviderError(f"No provider returned a valid live price for {symbol}; {' | '.join(errors)}")
