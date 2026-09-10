from app.analytics.risk_analytics_view import RiskAnalyticsView


def test_risk_snapshot_generation():
    view = RiskAnalyticsView()
    snapshot = view.generate_snapshot(
        equity=10000,
        exposure=2500,
        drawdown=0.05,
        margin_usage=0.3,
    )

    assert snapshot.equity == 10000
    assert snapshot.risk_state == "NORMAL"


def test_high_risk_alert():
    view = RiskAnalyticsView()
    snapshot = view.generate_snapshot(
        equity=10000,
        exposure=9000,
        drawdown=0.25,
        margin_usage=0.9,
    )

    assert snapshot.risk_state in ["HIGH_RISK", "MARGIN_WARNING"]
    assert len(snapshot.alerts) > 0
