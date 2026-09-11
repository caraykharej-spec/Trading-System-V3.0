from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.backtest.models import BacktestResult, TradeRecord
from app.backtest.monte_carlo import MonteCarloResult
from app.backtest.walk_forward import WalkForwardResult, WalkForwardWindow
from app.data.market_data import Candle
from app.research.models import (
    DatasetManifest,
    EvaluationSummary,
    ExperimentResult,
    ExperimentSpec,
    ParameterDefinition,
    ParameterSet,
    ParameterSpace,
    ResearchEvaluation,
    TrialResult,
)
from app.strategy_validation import (
    CostStressOutcome,
    CostStressReport,
    CostStressScenario,
    ForwardMode,
    ForwardObservation,
    ForwardValidationTracker,
    RegimeInterval,
    StrategyQualificationEngine,
    StrategyValidationEvidence,
    StrategyValidationPolicy,
    ValidationDecision,
    analyze_parameter_stability,
    analyze_regime_performance,
    build_chronological_split,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _trade(index: int, pnl: str = "10") -> TradeRecord:
    opened = NOW + timedelta(minutes=15 * index)
    return TradeRecord(
        position_id=f"p-{index}",
        symbol="BTC",
        direction="LONG",
        setup="test",
        entry_time=opened,
        entry_price=Decimal("100"),
        exit_time=opened + timedelta(minutes=15),
        exit_price=Decimal("101"),
        stop_loss=Decimal("99"),
        target=Decimal("102.5"),
        quantity=Decimal("1"),
        total_amount=Decimal("100"),
        leverage=Decimal("1"),
        realized_pnl=Decimal(pnl),
        commission=Decimal("0.1"),
        exit_reason="TARGET",
    )


def _result(return_percent: str = "8", trades: tuple[TradeRecord, ...] | None = None) -> BacktestResult:
    active_trades = trades if trades is not None else tuple(_trade(i) for i in range(4))
    return BacktestResult(
        initial_equity=Decimal("10000"),
        final_equity=Decimal("10800"),
        trades=active_trades,
        rejected_signals=0,
        open_positions_at_end=0,
        max_drawdown_percent=Decimal("8"),
        win_rate_percent=Decimal("75"),
        profit_factor=Decimal("2"),
        total_return_percent=Decimal(return_percent),
        max_concurrent_positions=2,
    )


def test_chronological_split_is_non_overlapping() -> None:
    candles = [
        Candle(
            symbol="BTC",
            timeframe="15m",
            timestamp=NOW + timedelta(minutes=15 * index),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("10"),
        )
        for index in range(12)
    ]
    split = build_chronological_split(candles, train_size=6, validation_size=3)
    assert split.train_end < split.validation_start
    assert split.validation_end < split.holdout_start
    assert split.holdout_end == candles[-1].timestamp


def test_forward_tracker_is_idempotent_and_detects_conflicts() -> None:
    tracker = ForwardValidationTracker()
    observation = ForwardObservation(
        signal_id="s1",
        timestamp=NOW,
        symbol="BTC",
        direction="LONG",
        mode=ForwardMode.PAPER,
        risk_approved=True,
        outcome_return_percent=Decimal("1"),
    )
    tracker.record(observation)
    tracker.record(observation)
    assert tracker.report().total_observations == 1

    with pytest.raises(ValueError):
        tracker.record(
            ForwardObservation(
                signal_id="s1",
                timestamp=NOW,
                symbol="BTC",
                direction="LONG",
                mode=ForwardMode.PAPER,
                risk_approved=True,
                outcome_return_percent=Decimal("-1"),
            )
        )


def test_regime_performance_segments_trades() -> None:
    trades = (_trade(0, "10"), _trade(1, "5"), _trade(4, "7"), _trade(5, "3"))
    intervals = (
        RegimeInterval("TRENDING", NOW, NOW + timedelta(minutes=30)),
        RegimeInterval(
            "RANGING",
            NOW + timedelta(minutes=45),
            NOW + timedelta(minutes=90),
        ),
    )
    report = analyze_regime_performance(trades, intervals)
    assert {item.label for item in report.regimes} == {"RANGING", "TRENDING"}
    assert report.qualified_regime_count(
        min_trades=1,
        min_profit_factor=Decimal("1"),
    ) == 2


def test_parameter_stability_uses_feasible_sensitivity() -> None:
    summary = EvaluationSummary(
        total_return_percent=Decimal("10"),
        max_drawdown_percent=Decimal("5"),
        win_rate_percent=Decimal("60"),
        profit_factor=Decimal("2"),
        trade_count=30,
        rejected_signals=0,
    )
    evaluation = ResearchEvaluation(summary=summary)
    spec = ExperimentSpec(
        name="stability",
        strategy_version="v1",
        datasets=DatasetManifest("train"),
        parameter_space=ParameterSpace(
            (ParameterDefinition("min_score", (Decimal("88"), Decimal("90"))),)
        ),
    )
    trials = (
        TrialResult(
            trial_id="a",
            parameters=ParameterSet.from_mapping({"min_score": Decimal("88")}),
            training=evaluation,
            validation=None,
            training_objective=Decimal("10"),
            selection_objective=Decimal("10"),
            validation_degradation_percent=None,
            feasible=True,
            violations=(),
        ),
        TrialResult(
            trial_id="b",
            parameters=ParameterSet.from_mapping({"min_score": Decimal("90")}),
            training=evaluation,
            validation=None,
            training_objective=Decimal("11"),
            selection_objective=Decimal("11"),
            validation_degradation_percent=None,
            feasible=True,
            violations=(),
        ),
    )
    result = ExperimentResult(spec=spec, trials=trials, best_trial=trials[1], created_at=NOW)
    report = analyze_parameter_stability(result, max_normalized_spread=Decimal("0.10"))
    assert report.stable
    assert report.feasible_trial_ratio == Decimal("1")


def test_qualification_requires_all_evidence_and_can_qualify() -> None:
    holdout = _result()
    walk_forward = WalkForwardResult(
        windows=(
            WalkForwardWindow(0, 10, 10, 15),
            WalkForwardWindow(5, 15, 15, 20),
        ),
        results=(_result("5"), _result("3")),
    )
    monte_carlo = MonteCarloResult(
        simulations=1000,
        initial_equity=Decimal("10000"),
        median_final_equity=Decimal("10800"),
        worst_final_equity=Decimal("9000"),
        best_final_equity=Decimal("12000"),
        median_return_percent=Decimal("8"),
        worst_return_percent=Decimal("-10"),
        best_return_percent=Decimal("20"),
        median_max_drawdown_percent=Decimal("12"),
        worst_max_drawdown_percent=Decimal("20"),
    )
    scenario = CostStressScenario(
        "stress",
        commission_percent=Decimal("0.1"),
        spread_percent=Decimal("0.1"),
        slippage_percent=Decimal("0.2"),
    )
    cost_stress = CostStressReport(
        baseline=_result("8"),
        outcomes=(
            CostStressOutcome(
                scenario=scenario,
                result=_result("7"),
                return_degradation_percent=Decimal("12.5"),
                drawdown_increase_points=Decimal("2"),
            ),
        ),
    )

    summary = EvaluationSummary(
        total_return_percent=Decimal("10"),
        max_drawdown_percent=Decimal("5"),
        win_rate_percent=Decimal("60"),
        profit_factor=Decimal("2"),
        trade_count=30,
        rejected_signals=0,
    )
    evaluation = ResearchEvaluation(summary=summary)
    spec = ExperimentSpec(
        name="qualification",
        strategy_version="v1",
        datasets=DatasetManifest("train"),
        parameter_space=ParameterSpace(
            (ParameterDefinition("min_score", (Decimal("88"), Decimal("90"))),)
        ),
    )
    trials = (
        TrialResult(
            trial_id="a",
            parameters=ParameterSet.from_mapping({"min_score": Decimal("88")}),
            training=evaluation,
            validation=None,
            training_objective=Decimal("10"),
            selection_objective=Decimal("10"),
            validation_degradation_percent=None,
            feasible=True,
            violations=(),
        ),
        TrialResult(
            trial_id="b",
            parameters=ParameterSet.from_mapping({"min_score": Decimal("90")}),
            training=evaluation,
            validation=None,
            training_objective=Decimal("10.5"),
            selection_objective=Decimal("10.5"),
            validation_degradation_percent=None,
            feasible=True,
            violations=(),
        ),
    )
    stability = analyze_parameter_stability(
        ExperimentResult(spec=spec, trials=trials, best_trial=trials[1], created_at=NOW),
        max_normalized_spread=Decimal("0.10"),
    )

    regime = analyze_regime_performance(
        holdout.trades,
        (
            RegimeInterval("TRENDING", NOW, NOW + timedelta(minutes=30)),
            RegimeInterval(
                "RANGING",
                NOW + timedelta(minutes=45),
                NOW + timedelta(minutes=90),
            ),
        ),
    )

    tracker = ForwardValidationTracker()
    for index, outcome in enumerate(("1", "-0.5", "0.8", "0.2")):
        tracker.record(
            ForwardObservation(
                signal_id=f"f-{index}",
                timestamp=NOW + timedelta(hours=index),
                symbol="BTC",
                direction="LONG",
                mode=ForwardMode.SHADOW,
                risk_approved=True,
                outcome_return_percent=Decimal(outcome),
            )
        )

    policy = StrategyValidationPolicy(
        min_oos_trades=4,
        min_walk_forward_windows=2,
        min_profitable_walk_forward_ratio=Decimal("1"),
        max_cost_stress_degradation_percent=Decimal("20"),
        max_parameter_normalized_spread=Decimal("0.10"),
        min_regime_trade_count=1,
        min_qualified_regimes=2,
        min_forward_observations=4,
        min_forward_hit_rate_percent=Decimal("50"),
    )
    report = StrategyQualificationEngine(policy).evaluate(
        StrategyValidationEvidence(
            holdout=holdout,
            walk_forward=walk_forward,
            monte_carlo=monte_carlo,
            cost_stress=cost_stress,
            parameter_stability=stability,
            regime=regime,
            forward=tracker.report(),
        )
    )
    assert report.decision is ValidationDecision.QUALIFIED
    assert report.qualified


def test_qualification_fails_closed_when_evidence_is_missing() -> None:
    report = StrategyQualificationEngine().evaluate(StrategyValidationEvidence())
    assert report.decision is ValidationDecision.HOLD
    assert not report.qualified
    assert all(not check.passed for check in report.checks)
