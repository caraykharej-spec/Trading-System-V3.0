from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.risk.risk_pipeline import ApprovedRiskPackage


@dataclass(frozen=True)
class LiveRiskLimits:
    max_risk_score: Decimal = Decimal("100")
    max_position_size: Decimal = Decimal("1000000")
    allow_execution_states: tuple[str, ...] = ("APPROVED_FOR_EXECUTION",)


@dataclass(frozen=True)
class LiveRiskDecision:
    approved: bool
    reason: str


class LiveRiskController:
    """Secondary production risk gate applied after the core RiskPipeline."""

    def __init__(self, limits: LiveRiskLimits | None = None) -> None:
        self.limits = limits or LiveRiskLimits()

    def evaluate(self, package: ApprovedRiskPackage) -> LiveRiskDecision:
        if not package.approved:
            return LiveRiskDecision(False, "core risk package not approved")
        if package.state not in self.limits.allow_execution_states:
            return LiveRiskDecision(False, f"risk state not executable: {package.state}")
        if package.position_size <= 0:
            return LiveRiskDecision(False, "position size must be positive")
        if package.position_size > self.limits.max_position_size:
            return LiveRiskDecision(False, "position size exceeds live limit")
        if package.risk_score > self.limits.max_risk_score:
            return LiveRiskDecision(False, "risk score exceeds live limit")
        return LiveRiskDecision(True, "live risk checks passed")
