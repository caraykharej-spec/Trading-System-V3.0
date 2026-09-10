from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.models import Position
from app.risk.risk_math import position_open_risk


@dataclass(frozen=True)
class CorrelationPair:
    first: str
    second: str
    coefficient: Decimal

    def __post_init__(self) -> None:
        validate_correlation(self.coefficient)
        if not self.first.strip() or not self.second.strip():
            raise ValueError("correlation symbols must not be empty")


@dataclass(frozen=True)
class CorrelationExposure:
    candidate_symbol: str
    correlated_risk: Decimal
    members: tuple[str, ...]


@dataclass(frozen=True)
class CorrelationMatrix:
    """Symmetric correlation lookup used for candidate cluster-risk checks."""

    pairs: tuple[CorrelationPair, ...] = ()

    def coefficient(self, first: str, second: str) -> Decimal:
        if first.upper() == second.upper():
            return Decimal("1")
        a = first.upper()
        b = second.upper()
        for pair in self.pairs:
            left = pair.first.upper()
            right = pair.second.upper()
            if {left, right} == {a, b}:
                return pair.coefficient
        return Decimal("0")

    def candidate_exposure(
        self,
        *,
        candidate_symbol: str,
        new_risk: Decimal,
        positions: list[Position],
        cluster_threshold: Decimal = Decimal("0.60"),
    ) -> CorrelationExposure:
        if new_risk < 0:
            raise ValueError("new_risk cannot be negative")
        validate_correlation(cluster_threshold)
        total = new_risk
        members: list[str] = [candidate_symbol]
        for position in positions:
            if position.status.value != "OPEN":
                continue
            coefficient = correlation_risk_multiplier(
                self.coefficient(candidate_symbol, position.symbol)
            )
            if coefficient <= 0:
                continue
            total += position_open_risk(position) * coefficient
            if coefficient >= cluster_threshold:
                members.append(position.symbol)
        return CorrelationExposure(candidate_symbol, total, tuple(dict.fromkeys(members)))


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
