"""Integration layer between strategy signals and risk approval."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RiskDecision:
    symbol: str
    approved: bool
    risk_score: Decimal
    reason: str
    position_size: Decimal


class RiskIntegration:
    """Validates strategy outputs before portfolio/execution layers."""

    def __init__(self, max_risk_score: Decimal = Decimal("100")):
        self.max_risk_score = max_risk_score

    def evaluate(self, signals: list[dict]) -> list[RiskDecision]:
        decisions = []

        for signal in signals:
            score = Decimal(str(signal.get("risk_score", 0)))
            approved = score <= self.max_risk_score

            decisions.append(
                RiskDecision(
                    symbol=str(signal.get("symbol", "")),
                    approved=approved,
                    risk_score=score,
                    reason="APPROVED" if approved else "RISK_LIMIT_EXCEEDED",
                    position_size=Decimal(str(signal.get("position_size", 0))),
                )
            )

        return decisions
