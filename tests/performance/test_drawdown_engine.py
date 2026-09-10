from app.performance.drawdown_engine import DrawdownEngine


def test_drawdown_tracking():
    engine = DrawdownEngine()

    engine.update(1000)
    snapshot = engine.update(900)

    assert snapshot.peak_equity == 1000
    assert snapshot.current_equity == 900
    assert snapshot.drawdown > 0
    assert snapshot.max_drawdown == snapshot.drawdown
