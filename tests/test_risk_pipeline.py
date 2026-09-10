from decimal import Decimal

from app.risk.risk_pipeline import RiskPipeline
from app.risk.integration import RiskDecision


def test_risk_pipeline_approval():
    decision = RiskDecision(
        symbol="BTC",
        approved=True,
        risk_score=Decimal("0.8"),
        reason="ok",
        position_size=Decimal("1"),
    )

    result = RiskPipeline().evaluate(decision)

    assert result.state == "APPROVED_FOR_EXECUTION"
    assert result.position_size == Decimal("1")


def test_risk_pipeline_rejection():
    decision = RiskDecision(
        symbol="BTC",
        approved=False,
        risk_score=Decimal("0"),
        reason="risk limit",
        position_size=Decimal("0"),
    )

    result = RiskPipeline().evaluate(decision)

    assert result.state == "REJECTED"
