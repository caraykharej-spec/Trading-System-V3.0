from app.analytics.risk_alerts import RiskAlertEngine, RiskAlertLevel


def test_high_margin_alert():
    engine = RiskAlertEngine()
    alerts = engine.evaluate(0.05, 0.90, 0.40)

    assert len(alerts) == 1
    assert alerts[0].level == RiskAlertLevel.HIGH
    assert alerts[0].alert_type == "MARGIN"


def test_drawdown_warning():
    engine = RiskAlertEngine()
    alerts = engine.evaluate(0.15, 0.20, 0.30)

    assert alerts[0].alert_type == "DRAWDOWN"
    assert alerts[0].level == RiskAlertLevel.WARNING
