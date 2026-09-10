from app.production_operation.strategy_execution_validation import (
    StrategyCheck,
    StrategyExecutionValidationEngine,
)


def test_strategy_validation_flow():
    engine = StrategyExecutionValidationEngine()

    engine.register_check(
        StrategyCheck(
            name="signal_generation",
            component="strategy_engine",
            passed=True,
        )
    )

    engine.register_check(
        StrategyCheck(
            name="ranking_output",
            component="ranking_engine",
            passed=True,
        )
    )

    report = engine.validate()

    assert report.passed is True
    assert len(report.checks) == 2


def test_strategy_validation_health():
    engine = StrategyExecutionValidationEngine()
    assert engine.health()["status"] == "healthy"
