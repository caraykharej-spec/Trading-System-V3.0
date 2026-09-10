from decimal import Decimal

from app.strategy.integration import StrategyCandidate
from app.strategy.strategy_pipeline import StrategyPipeline


def test_pipeline_accepts_signal():
    candidate = StrategyCandidate(
        symbol="BTC",
        opportunity_score=Decimal("85"),
        strategy_signal=None,
    )

    result = StrategyPipeline().process(
        [candidate],
        lambda item: "SIGNAL",
    )

    assert len(result) == 1
    assert result[0].status == "READY_FOR_RISK_REVIEW"
    assert result[0].signal == "SIGNAL"


def test_pipeline_rejects_failed_evaluation():
    candidate = StrategyCandidate(
        symbol="ETH",
        opportunity_score=Decimal("70"),
        strategy_signal=None,
    )

    result = StrategyPipeline().process(
        [candidate],
        lambda item: (_ for _ in ()).throw(ValueError()),
    )

    assert result[0].status.startswith("REJECTED")
