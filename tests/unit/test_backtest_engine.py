from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.backtest.engine import BacktestEngine
from app.backtest.models import BacktestConfig
from app.core.enums import SystemMode
from app.data.market_data import Candle
from app.strategy.strategy_engine import StrategyState


def candle(ts: datetime, o: str, h: str, l: str, c: str) -> Candle:
    return Candle("TEST", "15m", ts, Decimal(o), Decimal(h), Decimal(l), Decimal(c), Decimal("100"))


def test_backtest_fills_next_bar_and_hits_take_profit() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        candle(start, "100", "101", "99", "100"),
        candle(start.replace(minute=15), "100", "101", "99", "100"),
        candle(start.replace(minute=30), "100", "106", "99", "105"),
    ]
    source = {tf: [Candle("TEST", tf, start, Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("100")) for _ in range(3)] for tf in ("1d", "4h", "1h")}
    source["15m"] = bars

    signal = SimpleNamespace(
        state=StrategyState.READY_FOR_RISK_REVIEW,
        direction="LONG",
        setup="TEST_SETUP",
        stop_loss=Decimal("95"),
        target=Decimal("105"),
    )

    engine = BacktestEngine(BacktestConfig(initial_equity=Decimal("10000"), risk_per_trade_percent=Decimal("1")))
    with patch.object(engine, "_snapshots_at", return_value={"1d": object(), "4h": object(), "1h": object(), "15m": object()}), patch("app.backtest.engine.evaluate_strategy", return_value=signal):
        result = engine.run("TEST", source)

    assert len(result.trades) >= 1
    trade = result.trades[0]
    assert trade.entry_price == Decimal("100")
    assert trade.exit_reason == "TAKE_PROFIT"
    assert trade.realized_pnl > 0
    assert result.final_equity > result.initial_equity


def test_stop_loss_wins_when_both_levels_are_touched() -> None:
    signal = SimpleNamespace(direction="LONG", stop_loss=Decimal("95"), target=Decimal("105"))
    bar = candle(datetime(2026, 1, 1, tzinfo=timezone.utc), "100", "106", "94", "100")
    trade = SimpleNamespace(signal=signal)
    exit_price, reason = BacktestEngine._intrabar_exit(trade, bar)
    assert exit_price == Decimal("95")
    assert reason == "STOP_LOSS"
