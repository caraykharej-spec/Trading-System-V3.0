from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CorrelationPair:
    first: str
    second: str
    coefficient: Decimal


def validate_correlation(value: Decimal) -> None:
    if value < Decimal("-1") or value > Decimal("1"):
        raise ValueError("correlation must be between -1 and 1")


def correlation_risk_multiplier(value: Decimal) -> Decimal:
    """Conservative multiplier for shared directional risk."""
    validate_correlation(value)
    return max(Decimal("0"), value)


def correlated_risk(new_risk: Decimal, existing_risk: Decimal, correlation: Decimal) -> Decimal:
    if new_risk < 0 or existing_risk < 0:
        raise ValueError("risk cannot be negative")
    return new_risk + existing_risk * correlation_risk_multiplier(correlation)
