from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    price_tick: Decimal
    quantity_step: Decimal
    min_quantity: Decimal
    min_notional: Decimal | None = None
    max_leverage: Decimal | None = None

    def validate(self) -> None:
        if self.price_tick <= 0:
            raise ValueError("price_tick must be positive")
        if self.quantity_step <= 0:
            raise ValueError("quantity_step must be positive")
        if self.min_quantity < 0:
            raise ValueError("min_quantity cannot be negative")
        if self.min_notional is not None and self.min_notional < 0:
            raise ValueError("min_notional cannot be negative")
        if self.max_leverage is not None and self.max_leverage < 1:
            raise ValueError("max_leverage must be >= 1")
