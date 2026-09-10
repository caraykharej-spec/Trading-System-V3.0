from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.backtest.models import BacktestConfig
from app.backtest.portfolio import PortfolioBacktestEngine
from app.data.market_data import Candle
from app.strategy.strategy_engine import StrategyState


def bar(symbol: str, tf: str, minute: int, close: str = "100") -> Candle:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc).replace(minute=minute)
    return Candle(
        symbol,
        tf,
        ts,
        Decimal("100"),
        Decimal("101"),
        Decimal("99"),
        Decimal(close),
        Decimal("100"),
    )


def source(symbol: str) -> dict[str, list[Candle]]:
    return {
        tf: [bar(symbol, tf, 0), bar(symbol, tf, 15), bar(symbol, tf, 30)]
        for tf in ("1d", "4h", "1h", "15m")
    }


def test_portfolio_uses_shared_equity_and_records_curve() -> None:
    signal = SimpleNamespace(
        state=StrategyState.READY_FOR_RISK_REVIEW,
        direction="LONG",
        setup="TEST",
        stop_loss=Decimal("95"),
        target=Decimal("105"),
    )
    engine = PortfolioBacktestEngine(BacktestConfig(initial_equity=Decimal("10000")))
    snapshots = {"1d": object(), "4h": object(), "1h": object(), "15m": object()}
    with (
        patch.object(engine._helpers, "_snapshots_at", return_value=snapshots),
        patch("app.backtest.portfolio.evaluate_strategy", return_value=signal),
    ):
        result = engine.run({"A": source("A"), "B": source("B")})
    assert result.initial_equity == Decimal("10000")
    assert len(result.equity_curve) >= 2
    assert result.total_trades >= 1
