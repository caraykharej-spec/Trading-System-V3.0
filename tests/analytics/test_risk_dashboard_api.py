from app.analytics.risk_dashboard_api import RiskDashboardAPI, RiskDashboardSnapshot


class MockProvider:
    def get_risk_snapshot(self):
        return RiskDashboardSnapshot(
            risk_state="NORMAL",
            equity=10000,
            exposure=2000,
            margin_ratio=0.2,
            drawdown=0.05,
            alerts=[]
        )


def test_risk_dashboard_snapshot():
    api = RiskDashboardAPI(MockProvider())
    snapshot = api.get_snapshot()

    assert snapshot.risk_state == "NORMAL"
    assert snapshot.equity == 10000


def test_alert_feed():
    api = RiskDashboardAPI(MockProvider())
    assert api.get_alert_feed() == []
