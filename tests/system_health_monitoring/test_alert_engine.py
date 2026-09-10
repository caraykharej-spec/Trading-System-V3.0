from app.system_health_monitoring.alert_engine import AlertEngine


def test_alert_creation():
    engine = AlertEngine()
    alert = engine.create_alert("API", "critical", "API unavailable")

    assert alert.alert_type == "API"
    assert alert.severity == "critical"


def test_health_evaluation():
    engine = AlertEngine()
    alerts = engine.evaluate_health({"oracle": "failed", "runtime": "healthy"})

    assert len(alerts) == 1
    assert alerts[0].alert_type == "oracle"
