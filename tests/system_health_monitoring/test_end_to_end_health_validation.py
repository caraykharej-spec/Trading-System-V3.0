from app.system_health_monitoring.end_to_end_health_validation import EndToEndHealthValidator
from app.system_health_monitoring.trading_readiness_gate import TradingReadinessGate


def test_health_validation_pass():
    result = EndToEndHealthValidator().validate({"runtime": True, "api": True})
    assert result.passed is True


def test_trading_readiness_gate():
    result = TradingReadinessGate().evaluate(True)
    assert result.ready is True
