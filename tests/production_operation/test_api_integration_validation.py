from app.production_operation.api_integration_validation import (
    APIIntegrationValidationEngine,
    APICheck,
)


def test_api_validation_flow():
    engine = APIIntegrationValidationEngine()

    engine.register_check(
        APICheck(
            name="Storm Trade API Connectivity",
            component="exchange_api",
            passed=True,
        )
    )

    engine.register_check(
        APICheck(
            name="Oracle Connectivity",
            component="pyth_stork_oracle",
            passed=True,
        )
    )

    report = engine.validate()

    assert report.passed is True
    assert len(report.checks) == 2


def test_api_health():
    engine = APIIntegrationValidationEngine()
    health = engine.health()

    assert health["status"] == "healthy"
