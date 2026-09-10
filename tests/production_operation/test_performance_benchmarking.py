from app.production_operation.performance_benchmarking import PerformanceBenchmarkEngine


def test_performance_benchmark():
    engine = PerformanceBenchmarkEngine()
    engine.record_metric("api_latency", 120, "ms")
    engine.record_metric("strategy_runtime", 20, "ms")

    report = engine.benchmark()

    assert report.passed
    assert len(report.metrics) == 2


def test_performance_health():
    engine = PerformanceBenchmarkEngine()
    assert engine.health()["status"] == "healthy"
