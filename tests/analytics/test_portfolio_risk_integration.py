from app.analytics.portfolio_risk_integration import PortfolioRiskIntegration


def test_portfolio_risk_normal_state():
    snapshot = PortfolioRiskIntegration().create_snapshot(
        {
            "equity": 10000,
            "exposure": 2000,
            "margin_usage": 0.2,
            "drawdown": 0.05,
        }
    )

    assert snapshot.risk_state == "NORMAL"
    assert snapshot.equity == 10000


def test_portfolio_risk_high_state():
    snapshot = PortfolioRiskIntegration().create_snapshot(
        {
            "equity": 10000,
            "margin_usage": 0.9,
            "drawdown": 0.25,
        }
    )

    assert snapshot.risk_state == "HIGH"
