from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ScoreBreakdown:
    htf_trend: Decimal
    structure: Decimal
    setup: Decimal
    confirmation: Decimal
    liquidity: Decimal
    volatility: Decimal
    rr_quality: Decimal

    @property
    def total(self) -> Decimal:
        return min(Decimal("100"), sum((self.htf_trend, self.structure, self.setup, self.confirmation, self.liquidity, self.volatility, self.rr_quality)))


def score_opportunity(*, htf_trend: Decimal, structure: Decimal, setup: Decimal, confirmation: Decimal, liquidity: Decimal, volatility: Decimal, rr_quality: Decimal) -> ScoreBreakdown:
    values = (htf_trend, structure, setup, confirmation, liquidity, volatility, rr_quality)
    if any(value < 0 or value > weight for value, weight in zip(values, (20, 15, 25, 15, 10, 5, 10))):
        raise ValueError("score component exceeds its allocated weight")
    return ScoreBreakdown(*values)
