from app.reporting.report_integration_validator import ReportIntegrationValidator


def test_report_validation_success():
    validator = ReportIntegrationValidator()

    result = validator.validate(
        {
            "report_type": "daily",
            "generated_at": "2026-09-10T00:00:00",
            "sections": {},
        }
    )

    assert result.valid is True


def test_report_validation_failure():
    validator = ReportIntegrationValidator()

    result = validator.validate({"report_type": "daily"})

    assert result.valid is False
