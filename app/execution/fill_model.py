"""Execution fill simulation models for Phase 29."""

from dataclasses import dataclass


@dataclass
class FillModel:
    """Paper execution assumptions."""

    fee_rate: float = 0.0
    slippage_rate: float = 0.0

    def calculate_fill_price(self, reference_price: float, side: str) -> float:
        if side.upper() == "BUY":
            return reference_price * (1 + self.slippage_rate)
        return reference_price * (1 - self.slippage_rate)

    def calculate_fee(self, quantity: float, price: float) -> float:
        return quantity * price * self.fee_rate
