from decimal import Decimal

from app.strategy.integration import StrategyIntegration


def test_strategy_integration_ranking():
    engine = StrategyIntegration()

    result = engine.evaluate(
        [
            {"symbol": "BTC", "score": 90},
            {"symbol": "ETH", "score": 85},
        ]
    )

    assert result[0].symbol == "BTC"
    assert result[0].opportunity_score == Decimal("90")
