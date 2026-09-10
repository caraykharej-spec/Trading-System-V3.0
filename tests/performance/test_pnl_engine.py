from app.performance.pnl_engine import PNLEngine


def test_long_unrealized_pnl():
    engine = PNLEngine()
    assert engine.calculate_unrealized(100, 110, 1, "LONG") == 10


def test_short_realized_pnl():
    engine = PNLEngine()
    assert engine.calculate_realized(100, 90, 1, "SHORT") == 10
