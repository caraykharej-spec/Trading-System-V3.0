from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.risk.integration import RiskDecision


@dataclass(frozen=True)
class ApprovedRiskPackage:
    symbol: str
    approved: bool
    risk_score: Decimal
    position_size: Decimal
    state: str


class RiskPipeline:
    """Final risk gate between strategy signals and execution."""

    def evaluate(self, decision: RiskDecision) -> ApprovedRiskPackage:
        if not decision.approved:
            return ApprovedRiskPackage(
                symbol=decision.symbol,
                approved=False,
                risk_score=decision.risk_score,
                position_size=Decimal("0"),
                state="REJECTED",
            )

        return ApprovedRiskPackage(
            symbol=decision.symbol,
            approved=True,
            risk_score=decision.risk_score,
            position_size=decision.position_size,
            state="APPROVED_FOR_EXECUTION",
        )
