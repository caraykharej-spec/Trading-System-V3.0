from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class CostValue:
    """A normalized value with its original venue representation."""
    value: Decimal | None
    raw: str | None

    @property
    def known(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class StormMarketCostSnapshot:
    """Immutable cost evidence from one Storm `/markets` record."""
    symbol: str
    market_address: str
    observed_at: datetime
    protocol_fee_ratio: CostValue
    execution_fee_ton: CostValue
    rollover_fee_ratio: CostValue
    funding_period_seconds: int | None
    long_funding_ratio_per_period: CostValue
    short_funding_ratio_per_period: CostValue
    spread_ratio: CostValue
    max_price_impact_ratio: CostValue
    max_price_spread_ratio: CostValue
    liquidation_fee_ratio: CostValue


@dataclass(frozen=True)
class TonFeeEvidence:
    """Estimated and settled TON network fee; settlement is authoritative."""
    estimated_ton: Decimal | None = None
    reserved_ton: Decimal | None = None
    refunded_ton: Decimal | None = None
    settled_ton: Decimal | None = None
    transaction_hash: str | None = None

    def __post_init__(self) -> None:
        values = (self.estimated_ton, self.reserved_ton, self.refunded_ton, self.settled_ton)
        if any(value is not None and value < 0 for value in values):
            raise ValueError("TON fee values cannot be negative")

    @property
    def effective_ton(self) -> Decimal | None:
        if self.settled_ton is not None:
            return self.settled_ton
        if self.reserved_ton is not None and self.refunded_ton is not None:
            return self.reserved_ton - self.refunded_ton
        return self.estimated_ton

    @property
    def reconciled(self) -> bool:
        return self.settled_ton is not None and bool(self.transaction_hash)


@dataclass(frozen=True)
class StormCostEstimate:
    protocol_fee: Decimal
    funding_cost: Decimal
    spread_cost: Decimal | None
    ton_network_fee: Decimal | None

    @property
    def known_total(self) -> Decimal:
        return self.protocol_fee + self.funding_cost + (self.spread_cost or Decimal("0"))
