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
        values = (
            self.htf_trend,
            self.structure,
            self.setup,
            self.confirmation,
            self.liquidity,
            self.volatility,
            self.rr_quality,
        )
        return min(Decimal("100"), sum(values, Decimal("0")))


def score_opportunity(
    *,
    htf_trend: Decimal,
    structure: Decimal,
    setup: Decimal,
    confirmation: Decimal,
    liquidity: Decimal,
    volatility: Decimal,
    rr_quality: Decimal,
) -> ScoreBreakdown:
    values = (
        htf_trend,
        structure,
        setup,
        confirmation,
        liquidity,
        volatility,
        rr_quality,
    )
    weights = (
        Decimal("20"),
        Decimal("15"),
        Decimal("25"),
        Decimal("15"),
        Decimal("10"),
        Decimal("5"),
        Decimal("10"),
    )
    if any(value < 0 or value > weight for value, weight in zip(values, weights)):
        raise ValueError("score component exceeds its allocated weight")
    return ScoreBreakdown(*values)
