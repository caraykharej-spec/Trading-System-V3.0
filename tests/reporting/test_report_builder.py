from app.reporting.report_builder import ReportBuilder


def test_report_builder_creates_document():
    builder = ReportBuilder()
    report = builder.build("daily_trading_report", {"trades": 5})

    assert report.report_type == "daily_trading_report"
    assert report.content["trades"] == 5
