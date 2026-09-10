from app.system_health_monitoring.system_health_dashboard_api import SystemHealthDashboardAPI


def test_health_snapshot_creation():
    api = SystemHealthDashboardAPI()
    snapshot = api.create_snapshot("healthy", {"runtime": "ok"})

    assert snapshot.status == "healthy"
    assert snapshot.components["runtime"] == "ok"


def test_alert_feed():
    api = SystemHealthDashboardAPI()
    alerts = api.get_alert_feed(["test-alert"])

    assert alerts == ["test-alert"]
