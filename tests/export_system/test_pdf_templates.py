from app.export_system.pdf_templates import (
    TradingReportTemplate,
    RiskReportTemplate,
    PerformanceReportTemplate,
    StrategyReportTemplate,
)


def test_pdf_templates_creation():
    data = {"value": 1}

    assert TradingReportTemplate().render(data)["title"] == "Daily Trading Report"
    assert RiskReportTemplate().render(data)["title"] == "Risk Report"
    assert PerformanceReportTemplate().render(data)["title"] == "Performance Report"
    assert StrategyReportTemplate().render(data)["title"] == "Strategy Report"
