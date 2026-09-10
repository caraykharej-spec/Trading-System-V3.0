from app.reporting.report_aggregation import ReportAggregator


def test_report_aggregation_creation():
    aggregator = ReportAggregator()
    report = aggregator.build(
        "daily_trading",
        {"trades": 10, "pnl": 125.5}
    )

    assert report.report_type == "daily_trading"
    assert report.sections["trades"] == 10
    assert aggregator.validate(report)


def test_report_validation():
    aggregator = ReportAggregator()
    report = aggregator.build("risk_report", {})
    assert aggregator.validate(report)
