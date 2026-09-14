from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.backtest.diagnostics import SignalAttritionDiagnostics
from app.backtest.engine import BacktestEngine
from app.backtest.models import BacktestConfig
from app.data.market_data import Candle
from app.strategy.strategy_engine import StrategyState


_TIMEFRAME_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def _source(count: int) -> dict[str, list[Candle]]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    source: dict[str, list[Candle]] = {}
    for timeframe, minutes in _TIMEFRAME_MINUTES.items():
        rows: list[Candle] = []
        for index in range(count):
            ts = start + timedelta(minutes=minutes * index)
            rows.append(
                Candle(
                    "TEST",
                    timeframe,
                    ts,
                    Decimal("100"),
                    Decimal("101"),
                    Decimal("99"),
                    Decimal("100"),
                    Decimal("1000"),
                )
            )
        source[timeframe] = rows
    return source


def _snapshots() -> dict[str, object]:
    return {"1d": object(), "4h": object(), "1h": object(), "15m": object()}


def _signal(
    state: StrategyState,
    *,
    reasons: tuple[str, ...] = (),
    stop_loss: str = "95",
) -> SimpleNamespace:
    return SimpleNamespace(
        state=state,
        direction="LONG",
        setup="CONTINUATION",
        stop_loss=Decimal(stop_loss),
        target=Decimal("105"),
        rr=Decimal("2.5"),
        score=Decimal("90"),
        confidence=Decimal("90"),
        reasons=reasons,
    )


def test_signal_attrition_observes_exact_strategy_and_trade_path() -> None:
    engine = BacktestEngine()
    diagnostics = SignalAttritionDiagnostics()
    rejected = _signal(
        StrategyState.REJECTED,
        reasons=("score below minimum", "confidence below minimum"),
    )
    ready = _signal(StrategyState.READY_FOR_RISK_REVIEW)

    with (
        patch.object(engine, "_snapshots_at", return_value=_snapshots()),
        patch(
            "app.backtest.engine.evaluate_strategy",
            side_effect=[
                ValueError("No aligned HTF direction"),
                rejected,
                ready,
                ValueError("No valid entry/SL/target levels"),
            ],
        ),
    ):
        result = engine.run(
            "TEST",
            _source(4),
            diagnostic_observer=diagnostics.record,
        )

    payload = diagnostics.to_payload()
    assert payload["decision_points"] == 4
    assert payload["pre_signal_rejections"] == 2
    assert payload["pre_signal_reasons"] == {
        "NO_ALIGNED_HTF_DIRECTION": 1,
        "NO_VALID_LEVELS": 1,
    }
    assert payload["post_signal_rejections"] == 1
    assert payload["post_signal_reason_occurrences"] == {
        "confidence below minimum": 1,
        "score below minimum": 1,
    }
    assert payload["post_signal_multi_reason_decisions"] == 1
    assert payload["ready_for_risk_review"] == 1
    assert payload["entry_attempts"] == 1
    assert payload["entry_rejections"] == 0
    assert payload["trades_opened"] == 1
    assert payload["trades_by_setup"] == {"CONTINUATION": 1}
    assert payload["legacy_rejected_signals_equivalent"] == result.rejected_signals == 3
    assert len(result.trades) == 1


def test_entry_risk_rejection_is_visible_without_changing_legacy_rejected_count() -> None:
    engine = BacktestEngine(
        BacktestConfig(max_futures_capital_percent=Decimal("50"))
    )
    diagnostics = SignalAttritionDiagnostics()
    ready = _signal(StrategyState.READY_FOR_RISK_REVIEW, stop_loss="99.9")

    with (
        patch.object(engine, "_snapshots_at", side_effect=[_snapshots(), None]),
        patch("app.backtest.engine.evaluate_strategy", return_value=ready),
    ):
        result = engine.run(
            "TEST",
            _source(2),
            diagnostic_observer=diagnostics.record,
        )

    payload = diagnostics.to_payload()
    assert payload["ready_for_risk_review"] == 1
    assert payload["entry_attempts"] == 1
    assert payload["entry_rejections"] == 1
    assert payload["entry_reasons"] == {"FUTURES_CAPITAL_LIMIT": 1}
    assert payload["trades_opened"] == 0
    assert payload["legacy_rejected_signals_equivalent"] == 0
    assert result.rejected_signals == 0
    assert len(result.trades) == 0
