from app.performance.fee_engine import FeeEngine
from app.performance.slippage_model import SlippageModel


def test_fee_engine():
    fee = FeeEngine().calculate(1000, 0.001)
    assert fee.total_fee == 1.0


def test_slippage_model():
    result = SlippageModel().calculate(100, 101)
    assert result.cost == 1
