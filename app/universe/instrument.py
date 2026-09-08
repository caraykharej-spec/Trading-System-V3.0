from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class AssetClass(str, Enum):
    CRYPTO = "CRYPTO"
    EQUITY = "EQUITY"
    COMMODITY = "COMMODITY"
    FOREX = "FOREX"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: AssetClass
    base_asset: str
    quote_asset: str
    tradable: bool = True
    min_quantity: Decimal | None = None
    quantity_step: Decimal | None = None
    price_tick: Decimal | None = None

    def validate(self) -> None:
        if not self.symbol or not self.base_asset or not self.quote_asset:
            raise ValueError("Instrument identifiers cannot be empty")
        if self.min_quantity is not None and self.min_quantity < 0:
            raise ValueError("min_quantity cannot be negative")
        if self.quantity_step is not None and self.quantity_step <= 0:
            raise ValueError("quantity_step must be positive")
        if self.price_tick is not None and self.price_tick <= 0:
            raise ValueError("price_tick must be positive")
