from app.production_operation.e2e_system_validation import E2EValidationEngine


def test_e2e_validation_flow():
    engine = E2EValidationEngine()
    engine.register_component("market_data")
    engine.register_component("scanner")
    engine.register_component("strategy_engine")
    engine.register_component("risk_engine")
    engine.register_component("execution_engine")
    engine.register_component("portfolio_manager")

    report = engine.validate()

    assert report.passed
    assert len(report.checks) == 6


def test_e2e_health():
    engine = E2EValidationEngine()
    engine.register_component("runtime")

    health = engine.health()

    assert health["status"] == "healthy"
