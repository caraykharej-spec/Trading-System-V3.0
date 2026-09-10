from app.reporting.report_generator import ReportGenerator


def test_report_generator_types():
    generator = ReportGenerator()

    assert generator.daily_trading_report({}).report_type == "daily_trading"
    assert generator.performance_report({}).report_type == "performance"
    assert generator.risk_report({}).report_type == "risk"
    assert generator.strategy_report({}).report_type == "strategy"
    assert generator.portfolio_summary({}).report_type == "portfolio_summary"
