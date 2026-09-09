from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.models import Position
from app.portfolio.correlation import correlated_risk
from app.portfolio.exposure import position_risk, total_notional, total_risk


@dataclass(frozen=True)
class PortfolioPolicy:
    max_aggregate_risk_percent: Decimal = Decimal("4")
    max_correlated_risk_percent: Decimal = Decimal("2")
    max_futures_capital_percent: Decimal = Decimal("50")


@dataclass(frozen=True)
class PortfolioAssessment:
    approved: bool
    aggregate_risk: Decimal
    aggregate_risk_percent: Decimal
    correlated_risk: Decimal
    correlated_risk_percent: Decimal
    notional: Decimal
    reasons: tuple[str, ...]


def assess_portfolio(*, equity: Decimal, positions: list[Position], new_risk: Decimal, new_notional: Decimal, correlation: Decimal = Decimal("0"), policy: PortfolioPolicy = PortfolioPolicy()) -> PortfolioAssessment:
    if equity <= 0 or new_risk < 0 or new_notional < 0:
        raise ValueError("equity and portfolio values must be valid")
    existing_risk = total_risk(positions)
    aggregate = existing_risk + new_risk
    correlated = correlated_risk(new_risk, existing_risk, correlation)
    aggregate_pct = aggregate / equity * Decimal("100")
    correlated_pct = correlated / equity * Decimal("100")
    reasons: list[str] = []
    if aggregate_pct > policy.max_aggregate_risk_percent:
        reasons.append("aggregate open risk exceeds portfolio limit")
    if correlated_pct > policy.max_correlated_risk_percent:
        reasons.append("correlated risk exceeds portfolio limit")
    return PortfolioAssessment(not reasons, aggregate, aggregate_pct, correlated, correlated_pct, total_notional(positions) + new_notional, tuple(reasons))
