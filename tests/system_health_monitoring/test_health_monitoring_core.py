from app.system_health_monitoring.health_monitor_core import HealthMonitorCore


def test_health_monitor_core():
    result = HealthMonitorCore().run_check()
    assert result.status == "HEALTHY"
