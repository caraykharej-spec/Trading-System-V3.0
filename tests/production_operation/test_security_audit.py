from app.production_operation.security_audit import (
    SecurityAuditEngine,
    SecurityCheck,
)


def test_security_audit_flow():
    engine = SecurityAuditEngine()
    engine.register_check(
        SecurityCheck(
            name="credential_validation",
            component="secret_management",
            passed=True,
        )
    )

    report = engine.audit()

    assert report.passed is True
    assert len(report.checks) == 1


def test_security_health():
    engine = SecurityAuditEngine()
    assert engine.health()["status"] == "healthy"
