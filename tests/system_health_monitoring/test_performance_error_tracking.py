from app.system_health_monitoring.performance_monitor import PerformanceMonitor
from app.system_health_monitoring.error_tracking import ErrorTracker


def test_performance_monitor():
    metric = PerformanceMonitor().execution_latency(25.5)
    assert metric.metric == "execution_latency_ms"


def test_error_tracker():
    record = ErrorTracker().capture("APIError", "connection failed")
    assert record.error_type == "APIError"
