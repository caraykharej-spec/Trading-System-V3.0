from app.reporting.specialized_report_builders import (
    DailyTradingReportBuilder,
    PerformanceReportBuilder,
    RiskReportBuilder,
    StrategyReportBuilder,
    PortfolioSummaryGenerator,
    ReportValidator,
)


def test_specialized_report_builders():
    reports = [
        DailyTradingReportBuilder().build({"trades": 1}),
        PerformanceReportBuilder().build({"pnl": 100}),
        RiskReportBuilder().build({"state": "NORMAL"}),
        StrategyReportBuilder().build({"score": 90}),
        PortfolioSummaryGenerator().build({"equity": 10000}),
    ]

    validator = ReportValidator()

    assert all(validator.validate(report) for report in reports)
