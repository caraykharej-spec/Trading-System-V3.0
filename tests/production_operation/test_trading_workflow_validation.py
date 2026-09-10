from app.production_operation.trading_workflow_validation import TradingWorkflowValidator


def test_complete_trade_workflow():
    validator = TradingWorkflowValidator()

    for step in [
        "market_data",
        "signal_generation",
        "risk_approval",
        "execution",
        "position_update",
        "portfolio_update",
        "pnl_update",
    ]:
        validator.register_step(step)

    report = validator.validate()

    assert report.passed is True
    assert len(report.steps) == 7


def test_workflow_health():
    validator = TradingWorkflowValidator()
    assert validator.health()["status"] == "healthy"
