from app.production_operation.go_live_readiness import (
    GoLiveReadinessEngine,
    ReadinessCheck,
)


def test_go_live_readiness_report():
    engine = GoLiveReadinessEngine()
    engine.register_check(
        ReadinessCheck(
            name="system_validation",
            category="validation",
            passed=True,
        )
    )

    report = engine.generate_report()

    assert report.approved is True


def test_go_live_health():
    engine = GoLiveReadinessEngine()
    assert engine.health()["status"] == "healthy"
