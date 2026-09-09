from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.models import Position
from app.portfolio.correlation import correlated_risk
from app.portfolio.exposure import total_notional, total_risk


@dataclass(frozen=True)
class PortfolioPolicy:
    max_aggregate_risk_percent: Decimal = Decimal("4")
    max_correlated_risk_percent: Decimal = Decimal("2")
    max_futures_capital_percent: Decimal = Decimal("50")

    def validate(self) -> None:
        if not (Decimal("0") < self.max_aggregate_risk_percent <= Decimal("100")):
            raise ValueError("max_aggregate_risk_percent must be between 0 and 100")
        if not (Decimal("0") < self.max_correlated_risk_percent <= Decimal("100")):
            raise ValueError("max_correlated_risk_percent must be between 0 and 100")
        if not (Decimal("0") < self.max_futures_capital_percent <= Decimal("100")):
            raise ValueError("max_futures_capital_percent must be between 0 and 100")


@dataclass(frozen=True)
class PortfolioAssessment:
    approved: bool
    aggregate_risk: Decimal
    aggregate_risk_percent: Decimal
    correlated_risk: Decimal
    correlated_risk_percent: Decimal
    notional: Decimal
    reasons: tuple[str, ...]
    futures_capital_percent: Decimal = Decimal("0")


def assess_portfolio(
    *,
    equity: Decimal,
    positions: list[Position],
    new_risk: Decimal,
    new_notional: Decimal,
    correlation: Decimal = Decimal("0"),
    policy: PortfolioPolicy = PortfolioPolicy(),
    new_futures_capital: Decimal = Decimal("0"),
) -> PortfolioAssessment:
    if equity <= 0 or new_risk < 0 or new_notional < 0 or new_futures_capital < 0:
        raise ValueError("equity and portfolio values must be valid")
    policy.validate()
    existing_risk = total_risk(positions)
    aggregate = existing_risk + new_risk
    correlated = correlated_risk(new_risk, existing_risk, correlation)
    aggregate_pct = aggregate / equity * Decimal("100")
    correlated_pct = correlated / equity * Decimal("100")
    existing_futures = sum(
        position.total_amount
        for position in positions
        if position.status.value == "OPEN" and position.leverage > 1
    )
    futures_pct = (existing_futures + new_futures_capital) / equity * Decimal("100")
    reasons: list[str] = []
    if aggregate_pct > policy.max_aggregate_risk_percent:
        reasons.append("aggregate open risk exceeds portfolio limit")
    if correlated_pct > policy.max_correlated_risk_percent:
        reasons.append("correlated risk exceeds portfolio limit")
    if futures_pct > policy.max_futures_capital_percent:
        reasons.append("futures capital exceeds portfolio limit")
    return PortfolioAssessment(
        not reasons,
        aggregate,
        aggregate_pct,
        correlated,
        correlated_pct,
        total_notional(positions) + new_notional,
        tuple(reasons),
        futures_pct,
    )
