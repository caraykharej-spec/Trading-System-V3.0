from decimal import Decimal

from app.risk.integration import RiskIntegration


def test_risk_approval():
    engine = RiskIntegration()

    result = engine.evaluate([
        {
            "symbol": "BTC",
            "risk_score": "25",
            "position_size": "0.1",
        }
    ])

    assert result[0].approved is True
    assert result[0].symbol == "BTC"
    assert result[0].risk_score == Decimal("25")


def test_risk_rejection():
    engine = RiskIntegration(max_risk_score=Decimal("50"))

    result = engine.evaluate([
        {
            "symbol": "ETH",
            "risk_score": "75",
        }
    ])

    assert result[0].approved is False
