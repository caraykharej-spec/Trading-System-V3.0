from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CostBreakdown:
    """Deterministic execution/funding cost components for historical simulation."""

    entry_price: Decimal
    exit_price: Decimal
    entry_cost: Decimal
    exit_cost: Decimal
    funding_cost: Decimal


@dataclass(frozen=True)
class BacktestCostModel:
    """Models spread, slippage, commissions, and signed daily funding."""

    commission_percent: Decimal = Decimal("0")
    spread_percent: Decimal = Decimal("0")
    slippage_percent: Decimal = Decimal("0")
    funding_rate_percent_per_day: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.commission_percent < 0:
            raise ValueError("commission_percent must be non-negative")
        if self.spread_percent < 0:
            raise ValueError("spread_percent must be non-negative")
        if self.slippage_percent < 0:
            raise ValueError("slippage_percent must be non-negative")

    def entry_price(self, direction: str, raw_price: Decimal) -> Decimal:
        half_spread = self.spread_percent / Decimal("200")
        slippage = self.slippage_percent / Decimal("100")
        if direction == "LONG":
            return raw_price * (Decimal("1") + half_spread + slippage)
        if direction == "SHORT":
            return raw_price * (Decimal("1") - half_spread - slippage)
        raise ValueError(f"Unsupported direction: {direction}")

    def exit_price(self, direction: str, raw_price: Decimal) -> Decimal:
        half_spread = self.spread_percent / Decimal("200")
        slippage = self.slippage_percent / Decimal("100")
        if direction == "LONG":
            return raw_price * (Decimal("1") - half_spread - slippage)
        if direction == "SHORT":
            return raw_price * (Decimal("1") + half_spread + slippage)
        raise ValueError(f"Unsupported direction: {direction}")

    def commission(self, notional: Decimal) -> Decimal:
        return notional * self.commission_percent / Decimal("100")

    def funding(self, direction: str, notional: Decimal, minutes: int) -> Decimal:
        if minutes < 0:
            raise ValueError("minutes must be non-negative")
        daily = notional * self.funding_rate_percent_per_day / Decimal("100")
        amount = daily * Decimal(minutes) / Decimal("1440")
        if direction == "LONG":
            return amount
        if direction == "SHORT":
            return -amount
        raise ValueError(f"Unsupported direction: {direction}")
