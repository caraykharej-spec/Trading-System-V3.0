from datetime import datetime, timezone
from decimal import Decimal

from app.backtest.monte_carlo import run_monte_carlo
from app.backtest.models import TradeRecord


def trade(pnl: str, commission: str = "0") -> TradeRecord:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TradeRecord(
        position_id=pnl,
        symbol="TEST",
        direction="LONG",
        setup="TEST",
        entry_time=ts,
        entry_price=Decimal("100"),
        exit_time=ts,
        exit_price=Decimal("100"),
        stop_loss=Decimal("95"),
        target=Decimal("105"),
        quantity=Decimal("1"),
        total_amount=Decimal("1000"),
        leverage=Decimal("1"),
        realized_pnl=Decimal(pnl),
        commission=Decimal(commission),
        exit_reason="TEST",
    )


def test_monte_carlo_uses_real_initial_equity_scale() -> None:
    result = run_monte_carlo((trade("100"), trade("-50")), simulations=20, seed=7, initial_equity=Decimal("10000"))
    assert result.initial_equity == Decimal("10000")
    assert result.median_final_equity == Decimal("10050")
    assert result.median_return_percent == Decimal("0.5")


def test_bootstrap_is_deterministic() -> None:
    trades = (trade("100"), trade("-50"), trade("25"))
    a = run_monte_carlo(trades, simulations=30, seed=99, initial_equity=Decimal("10000"), bootstrap=True)
    b = run_monte_carlo(trades, simulations=30, seed=99, initial_equity=Decimal("10000"), bootstrap=True)
    assert a == b


def test_slippage_and_commission_stress_reduce_equity() -> None:
    base = run_monte_carlo((trade("100", "2"),), simulations=10, seed=1, initial_equity=Decimal("10000"))
    stressed = run_monte_carlo(
        (trade("100", "2"),), simulations=10, seed=1, initial_equity=Decimal("10000"),
        slippage_stress_percent=Decimal("0.1"), commission_stress_multiplier=Decimal("2")
    )
    assert stressed.median_final_equity < base.median_final_equity
