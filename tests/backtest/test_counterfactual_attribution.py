from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.backtest.counterfactual_attribution import (
    build_counterfactual_gate_attribution,
    validate_counterfactual_gate_attribution,
)
from app.backtest.diagnostics import BacktestDiagnosticEvent
from app.backtest.models import TradeRecord


def _ts(hour: int) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=timezone.utc)


def _trade(position_id: str, direction: str, pnl: str, hour: int) -> TradeRecord:
    return TradeRecord(
        position_id=position_id,
        symbol="TEST",
        direction=direction,
        setup="CONTINUATION",
        entry_time=_ts(hour),
        entry_price=Decimal("100"),
        exit_time=_ts(hour) + timedelta(minutes=15),
        exit_price=Decimal("101"),
        stop_loss=Decimal("95"),
        target=Decimal("105"),
        quantity=Decimal("1"),
        total_amount=Decimal("100"),
        leverage=Decimal("1"),
        realized_pnl=Decimal(pnl),
        commission=Decimal("0"),
        exit_reason="TEST",
        funding_cost=Decimal("0"),
    )


def test_exact_single_gate_release_and_direction_performance() -> None:
    events = (
        BacktestDiagnosticEvent(
            _ts(1),
            "STRATEGY_PRE_SIGNAL_REJECT",
            reasons=("NO_ALIGNED_HTF_DIRECTION",),
        ),
        BacktestDiagnosticEvent(
            _ts(2),
            "STRATEGY_SIGNAL_REJECT",
            reasons=("score below minimum",),
            direction="LONG",
            setup="CONTINUATION",
            rr=Decimal("3"),
            score=Decimal("89"),
            confidence=Decimal("95"),
        ),
        BacktestDiagnosticEvent(
            _ts(3),
            "STRATEGY_SIGNAL_REJECT",
            reasons=("score below minimum", "confidence below minimum"),
            direction="SHORT",
            setup="CONTINUATION",
            rr=Decimal("3"),
            score=Decimal("80"),
            confidence=Decimal("80"),
        ),
        BacktestDiagnosticEvent(
            _ts(4),
            "READY_FOR_RISK_REVIEW",
            direction="LONG",
            setup="CONTINUATION",
            rr=Decimal("3"),
            score=Decimal("95"),
            confidence=Decimal("95"),
        ),
        BacktestDiagnosticEvent(
            _ts(5),
            "ENTRY_REJECT",
            reasons=("AGGREGATE_RISK_LIMIT",),
            direction="LONG",
            setup="CONTINUATION",
            rr=Decimal("3"),
            score=Decimal("95"),
            confidence=Decimal("95"),
        ),
        BacktestDiagnosticEvent(
            _ts(6),
            "READY_FOR_RISK_REVIEW",
            direction="SHORT",
            setup="CONTINUATION",
            rr=Decimal("3"),
            score=Decimal("96"),
            confidence=Decimal("96"),
        ),
        BacktestDiagnosticEvent(
            _ts(7),
            "TRADE_OPENED",
            direction="SHORT",
            setup="CONTINUATION",
            rr=Decimal("3"),
            score=Decimal("96"),
            confidence=Decimal("96"),
        ),
    )
    trades = (_trade("1", "SHORT", "25", 7),)

    payload = build_counterfactual_gate_attribution(events, trades)

    score_gate = payload["post_signal_gate_sensitivity"]["MIN_SCORE"]
    assert score_gate["reason_occurrences"] == 2
    assert score_gate["exact_single_gate_release_candidates"] == 1
    assert score_gate["exact_single_gate_release_by_direction"] == {"LONG": 1}
    assert payload["post_signal_multi_gate_rejections"] == 1
    assert payload["pre_signal_observed_attrition"] == {
        "NO_ALIGNED_HTF_DIRECTION": 1
    }
    assert payload["risk_gate_candidate_sensitivity"]["AGGREGATE_RISK_LIMIT"][
        "candidate_count"
    ] == 1
    assert payload["direction_flow"]["LONG"]["ready_for_risk_review"] == 1
    assert payload["direction_flow"]["LONG"]["entry_rejections"] == 1
    assert payload["direction_flow"]["SHORT"]["trades_opened"] == 1
    assert payload["direction_flow"]["SHORT"]["realized_trade_performance"][
        "net_pnl"
    ] == Decimal("25")

    validate_counterfactual_gate_attribution(
        payload,
        expected_ready=2,
        expected_entry_rejections=1,
        expected_trades=1,
        trades=trades,
    )


def test_risk_quality_summary_is_descriptive_only() -> None:
    events = (
        BacktestDiagnosticEvent(
            _ts(1),
            "ENTRY_REJECT",
            reasons=("FUTURES_CAPITAL_LIMIT",),
            direction="LONG",
            rr=Decimal("2.5"),
            score=Decimal("91"),
            confidence=Decimal("92"),
        ),
        BacktestDiagnosticEvent(
            _ts(2),
            "ENTRY_REJECT",
            reasons=("FUTURES_CAPITAL_LIMIT",),
            direction="SHORT",
            rr=Decimal("3.5"),
            score=Decimal("99"),
            confidence=Decimal("98"),
        ),
    )
    payload = build_counterfactual_gate_attribution(events, ())
    risk = payload["risk_gate_candidate_sensitivity"]["FUTURES_CAPITAL_LIMIT"]

    assert risk["candidate_count"] == 2
    assert risk["by_direction"] == {"LONG": 1, "SHORT": 1}
    assert risk["signal_quality"]["rr"]["average"] == Decimal("3.0")
    assert "no causal trade-count or PnL counterfactual" in risk["interpretation"]


def test_validation_fails_closed_on_trade_or_pnl_mismatch() -> None:
    events = (
        BacktestDiagnosticEvent(
            _ts(1),
            "READY_FOR_RISK_REVIEW",
            direction="LONG",
        ),
        BacktestDiagnosticEvent(
            _ts(2),
            "TRADE_OPENED",
            direction="LONG",
        ),
    )
    trades = (_trade("1", "LONG", "10", 2),)
    payload = build_counterfactual_gate_attribution(events, trades)

    with pytest.raises(RuntimeError, match="trade-open accounting mismatch"):
        validate_counterfactual_gate_attribution(
            payload,
            expected_ready=1,
            expected_entry_rejections=0,
            expected_trades=2,
            trades=trades,
        )

    broken = build_counterfactual_gate_attribution(events, trades)
    broken["direction_flow"]["LONG"]["realized_trade_performance"]["net_pnl"] = Decimal("11")
    with pytest.raises(RuntimeError, match="PnL accounting mismatch"):
        validate_counterfactual_gate_attribution(
            broken,
            expected_ready=1,
            expected_entry_rejections=0,
            expected_trades=1,
            trades=trades,
        )
