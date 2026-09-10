from app.production_operation.data_pipeline_validation import (
    DataPipelineValidationEngine,
    PipelineCheck,
)


def test_pipeline_validation_flow():
    engine = DataPipelineValidationEngine()
    engine.register_check(
        PipelineCheck(
            name="market_data_connection",
            component="market_data",
            passed=True,
        )
    )

    report = engine.validate()

    assert report.passed is True
    assert len(report.checks) == 1


def test_pipeline_health():
    engine = DataPipelineValidationEngine()
    assert engine.health()["status"] == "healthy"
