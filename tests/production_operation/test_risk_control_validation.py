from app.production_operation.risk_control_validation import (
    RiskCheck,
    RiskControlValidationEngine,
)


def test_risk_validation_flow():
    engine = RiskControlValidationEngine()
    engine.register_check(
        RiskCheck(
            name="position_risk_check",
            component="position_risk",
            passed=True,
        )
    )

    report = engine.validate()

    assert report.passed is True
    assert len(report.checks) == 1


def test_risk_health():
    engine = RiskControlValidationEngine()
    assert engine.health()["status"] == "healthy"
