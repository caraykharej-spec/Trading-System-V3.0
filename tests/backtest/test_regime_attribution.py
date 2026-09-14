from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.backtest.diagnostics import BacktestDiagnosticEvent
from app.backtest.models import TradeRecord
from app.backtest.regime_attribution import (
    RegimePoint,
    attribute_regime_evidence,
    validate_regime_attribution,
)


def _ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=timezone.utc)


def _trade(
    position_id: str,
    entry_time: datetime,
    pnl: str,
) -> TradeRecord:
    return TradeRecord(
        position_id=position_id,
        symbol="TEST",
        direction="LONG",
        setup="CONTINUATION",
        entry_time=entry_time,
        entry_price=Decimal("100"),
        exit_time=entry_time + timedelta(hours=1),
        exit_price=Decimal("101"),
        stop_loss=Decimal("95"),
        target=Decimal("105"),
        quantity=Decimal("1"),
        total_amount=Decimal("100"),
        leverage=Decimal("1"),
        realized_pnl=Decimal(pnl),
        commission=Decimal("0"),
        exit_reason="TARGET",
        funding_cost=Decimal("0"),
    )


def test_regime_attribution_reconciles_decisions_entries_and_pnl() -> None:
    timeline = (
        RegimePoint(_ts(1), "TRENDING_BULL", "NORMAL"),
        RegimePoint(_ts(3), "TRENDING_BEAR", "HIGH"),
    )
    events = (
        BacktestDiagnosticEvent(_ts(1, 1), "STRATEGY_PRE_SIGNAL_REJECT"),
        BacktestDiagnosticEvent(_ts(1, 2), "READY_FOR_RISK_REVIEW"),
        BacktestDiagnosticEvent(_ts(1, 2), "TRADE_OPENED"),
        BacktestDiagnosticEvent(_ts(3, 1), "STRATEGY_SIGNAL_REJECT"),
        BacktestDiagnosticEvent(_ts(3, 2), "READY_FOR_RISK_REVIEW"),
        BacktestDiagnosticEvent(_ts(3, 2), "ENTRY_REJECT"),
    )
    trades = (_trade("bull-1", _ts(1, 2), "25"),)

    payload = attribute_regime_evidence(
        events,
        trades,
        timeline,
        initial_equity=Decimal("10000"),
    )

    assert payload["event_counts_by_regime"]["TRENDING_BULL"] == {
        "DECISION_POINTS": 2,
        "READY_FOR_RISK_REVIEW": 1,
        "STRATEGY_PRE_SIGNAL_REJECT": 1,
        "TRADE_OPENED": 1,
    }
    assert payload["event_counts_by_regime"]["TRENDING_BEAR"] == {
        "DECISION_POINTS": 2,
        "ENTRY_REJECT": 1,
        "READY_FOR_RISK_REVIEW": 1,
        "STRATEGY_SIGNAL_REJECT": 1,
    }
    bull = payload["trade_performance_by_entry_regime"]["TRENDING_BULL"]
    assert bull["trade_count"] == 1
    assert bull["wins"] == 1
    assert bull["net_pnl"] == Decimal("25")
    assert bull["net_pnl_percent_initial_equity"] == Decimal("0.2500")

    validate_regime_attribution(
        payload,
        expected_decision_points=4,
        expected_ready=2,
        expected_entry_rejections=1,
        expected_trades=1,
        trades=trades,
    )


def test_trade_performance_is_separated_by_entry_regime() -> None:
    timeline = (
        RegimePoint(_ts(1), "TRENDING_BULL", "LOW"),
        RegimePoint(_ts(2), "RANGING", "NORMAL"),
    )
    events = (
        BacktestDiagnosticEvent(_ts(1, 1), "READY_FOR_RISK_REVIEW"),
        BacktestDiagnosticEvent(_ts(1, 1), "TRADE_OPENED"),
        BacktestDiagnosticEvent(_ts(2, 1), "READY_FOR_RISK_REVIEW"),
        BacktestDiagnosticEvent(_ts(2, 1), "TRADE_OPENED"),
    )
    trades = (
        _trade("winner", _ts(1, 1), "30"),
        _trade("loser", _ts(2, 1), "-10"),
    )

    payload = attribute_regime_evidence(
        events,
        trades,
        timeline,
        initial_equity=Decimal("10000"),
    )

    bull = payload["trade_performance_by_entry_regime"]["TRENDING_BULL"]
    ranging = payload["trade_performance_by_entry_regime"]["RANGING"]
    assert bull["profit_factor"] is None
    assert bull["win_rate_percent"] == Decimal("100")
    assert ranging["profit_factor"] == Decimal("0")
    assert ranging["win_rate_percent"] == Decimal("0")


def test_attribution_fails_closed_without_completed_daily_regime() -> None:
    timeline = (RegimePoint(_ts(2), "TRENDING_BULL", "NORMAL"),)
    event = BacktestDiagnosticEvent(_ts(1, 12), "STRATEGY_PRE_SIGNAL_REJECT")

    with pytest.raises(ValueError, match="no completed daily regime"):
        attribute_regime_evidence(
            (event,),
            (),
            timeline,
            initial_equity=Decimal("10000"),
        )
