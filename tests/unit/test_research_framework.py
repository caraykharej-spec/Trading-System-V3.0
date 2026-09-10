from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3

import pytest

from app.backtest.models import BacktestResult
from app.backtest.portfolio import PortfolioBacktestResult
from app.backtest.walk_forward import WalkForwardResult, WalkForwardWindow
from app.data.market_data import Candle
from app.research import (
    BacktestResearchEvaluator,
    DatasetManifest,
    EvaluationSummary,
    ExperimentResult,
    ExperimentRunner,
    ExperimentSpec,
    ObjectiveMetric,
    ParameterDefinition,
    ParameterSet,
    ParameterSpace,
    PortfolioResearchEvaluator,
    ResearchConstraints,
    ResearchEvaluation,
    ResearchSpaceTooLargeError,
    SQLiteExperimentRegistry,
    SearchMethod,
    StrategyRuleParameterPolicy,
    WalkForwardResearchEvaluator,
    analyze_parameter_sensitivity,
    enumerate_parameter_sets,
    fingerprint_candles,
    strategy_rules_from_parameters,
)


UTC = timezone.utc


def _summary(
    total_return: str,
    *,
    drawdown: str = "5",
    trades: int = 10,
    profit_factor: str = "2",
    windows: int = 0,
) -> ResearchEvaluation:
    return ResearchEvaluation(
        summary=EvaluationSummary(
            total_return_percent=Decimal(total_return),
            max_drawdown_percent=Decimal(drawdown),
            win_rate_percent=Decimal("60"),
            profit_factor=Decimal(profit_factor),
            trade_count=trades,
            rejected_signals=0,
            window_count=windows,
        )
    )


def _backtest_result(
    total_return: str = "5", *, drawdown: str = "2"
) -> BacktestResult:
    initial = Decimal("10000")
    return BacktestResult(
        initial_equity=initial,
        final_equity=initial * (Decimal("1") + Decimal(total_return) / Decimal("100")),
        trades=(),
        rejected_signals=3,
        open_positions_at_end=0,
        max_drawdown_percent=Decimal(drawdown),
        win_rate_percent=Decimal("0"),
        profit_factor=None,
        total_return_percent=Decimal(total_return),
        max_concurrent_positions=0,
    )


def _space(*values: str) -> ParameterSpace:
    return ParameterSpace(
        (
            ParameterDefinition(
                "min_score",
                tuple(Decimal(value) for value in values),
            ),
        )
    )


def test_parameter_policy_is_deny_by_default_and_cannot_weaken_strategy() -> None:
    policy = StrategyRuleParameterPolicy()

    with pytest.raises(ValueError, match="cannot lower"):
        policy.validate_space(
            ParameterSpace(
                (ParameterDefinition("min_rr", (Decimal("2.4"),)),)
            )
        )

    with pytest.raises(ValueError, match="not approved"):
        policy.validate_space(
            ParameterSpace(
                (
                    ParameterDefinition(
                        "risk_per_trade_percent",
                        (Decimal("0.5"),),
                    ),
                )
            )
        )


def test_parameter_enumeration_is_bounded_and_random_search_reproducible() -> None:
    space = ParameterSpace(
        (
            ParameterDefinition("min_score", (Decimal("90"), Decimal("92"))),
            ParameterDefinition(
                "min_confidence", (Decimal("90"), Decimal("95"))
            ),
        )
    )

    grid = enumerate_parameter_sets(
        space, method=SearchMethod.GRID, max_trials=4, seed=7
    )
    assert len(grid) == 4
    assert len({item.stable_key for item in grid}) == 4

    with pytest.raises(ResearchSpaceTooLargeError, match="4 combinations"):
        enumerate_parameter_sets(
            space, method=SearchMethod.GRID, max_trials=3, seed=7
        )

    first = enumerate_parameter_sets(
        space, method=SearchMethod.RANDOM, max_trials=2, seed=99
    )
    second = enumerate_parameter_sets(
        space, method=SearchMethod.RANDOM, max_trials=2, seed=99
    )
    assert first == second


def test_dataset_fingerprint_is_stable_and_sensitive_to_market_data() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [
        Candle(
            symbol="BTC/USDT",
            timeframe="15m",
            timestamp=base + timedelta(minutes=15 * index),
            open=Decimal("100") + index,
            high=Decimal("101") + index,
            low=Decimal("99") + index,
            close=Decimal("100.5") + index,
            volume=Decimal("1000") + index,
        )
        for index in range(2)
    ]
    source = {"15m": list(reversed(candles))}

    first = fingerprint_candles("BTC/USDT", source)
    second = fingerprint_candles("BTC/USDT", {"15m": candles})
    changed = replace(candles[1], close=Decimal("999"))
    third = fingerprint_candles(
        "BTC/USDT", {"15m": [candles[0], changed]}
    )

    assert first == second
    assert first != third
    assert len(first) == 64


def test_strategy_rules_from_parameters_only_changes_approved_fields() -> None:
    rules = strategy_rules_from_parameters(
        ParameterSet.from_mapping(
            {
                "min_rr": Decimal("3"),
                "min_score": Decimal("92"),
                "min_confidence": Decimal("94"),
            }
        )
    )

    assert rules.min_rr == Decimal("3")
    assert rules.min_score == Decimal("92")
    assert rules.min_confidence == Decimal("94")


def test_experiment_runner_uses_validation_guard_and_preserves_holdout_boundary() -> None:
    spec = ExperimentSpec(
        name="score-threshold-stability",
        strategy_version="v3-phase23",
        datasets=DatasetManifest("train-hash", "validation-hash", "untouched-holdout"),
        parameter_space=_space("90", "92"),
        objective=ObjectiveMetric.TOTAL_RETURN_PERCENT,
        max_trials=2,
        constraints=ResearchConstraints(
            min_trades=5,
            max_drawdown_percent=Decimal("20"),
            min_profit_factor=Decimal("1"),
            max_validation_degradation_percent=Decimal("25"),
        ),
    )

    def training(parameters: ParameterSet) -> ResearchEvaluation:
        return _summary("10" if parameters.get("min_score") == Decimal("90") else "12")

    def validation(parameters: ParameterSet) -> ResearchEvaluation:
        return _summary("9" if parameters.get("min_score") == Decimal("90") else "6")

    result = ExperimentRunner().run(
        spec,
        training_evaluator=training,
        validation_evaluator=validation,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert len(result.trials) == 2
    assert result.trials[0].feasible is True
    assert result.trials[1].feasible is False
    assert "objective degradation" in result.trials[1].violations[0]
    assert result.best_trial is not None
    assert result.best_trial.parameters.get("min_score") == Decimal("90")
    assert result.spec.datasets.holdout_fingerprint == "untouched-holdout"


def test_validation_evaluator_must_match_dataset_manifest() -> None:
    spec = ExperimentSpec(
        name="mismatch",
        strategy_version="v3",
        datasets=DatasetManifest("train", "validation"),
        parameter_space=_space("90"),
    )

    with pytest.raises(ValueError, match="validation evaluator"):
        ExperimentRunner().run(spec, training_evaluator=lambda _: _summary("1"))


def test_experiment_id_is_reproducible_and_data_versioned() -> None:
    spec = ExperimentSpec(
        name="reproducible",
        strategy_version="strategy-abc123",
        datasets=DatasetManifest("train-v1"),
        parameter_space=_space("90", "91"),
        seed=123,
    )
    same = replace(spec)
    changed_data = replace(spec, datasets=DatasetManifest("train-v2"))

    assert spec.experiment_id == same.experiment_id
    assert spec.experiment_id != changed_data.experiment_id


def test_sqlite_registry_is_idempotent_and_detects_conflicts(tmp_path) -> None:
    connection = sqlite3.connect(tmp_path / "research.db")
    registry = SQLiteExperimentRegistry(connection)
    spec = ExperimentSpec(
        name="registry",
        strategy_version="v3",
        datasets=DatasetManifest("train"),
        parameter_space=_space("90"),
    )
    result = ExperimentRunner().run(
        spec,
        training_evaluator=lambda _: _summary("4"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert registry.save(result) is True
    assert registry.save(result) is False
    stored = registry.get(spec.experiment_id)
    assert stored is not None
    assert stored.name == "registry"
    assert len(registry.list_all()) == 1

    conflicting = ExperimentResult(
        spec=result.spec,
        trials=(),
        best_trial=None,
        created_at=result.created_at,
    )
    with pytest.raises(RuntimeError, match="conflict"):
        registry.save(conflicting)
    connection.close()


def test_sensitivity_report_exposes_parameter_stability() -> None:
    spec = ExperimentSpec(
        name="sensitivity",
        strategy_version="v3",
        datasets=DatasetManifest("train"),
        parameter_space=_space("90", "91", "92"),
        objective=ObjectiveMetric.TOTAL_RETURN_PERCENT,
        max_trials=3,
    )

    def evaluator(parameters: ParameterSet) -> ResearchEvaluation:
        value = parameters.get("min_score")
        assert isinstance(value, Decimal)
        return _summary(str(value - Decimal("85")))

    result = ExperimentRunner().run(
        spec,
        training_evaluator=evaluator,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    report = analyze_parameter_sensitivity(result)

    assert len(report.parameters) == 1
    assert report.parameters[0].parameter_name == "min_score"
    assert len(report.parameters[0].points) == 3
    assert report.parameters[0].mean_objective_spread == Decimal("2")


def test_backtest_research_evaluator_injects_controlled_strategy_rules(monkeypatch) -> None:
    seen = []

    def fake_run(self, symbol, candles, evaluation_start=None):
        seen.append((self.rules, symbol, evaluation_start, candles))
        return _backtest_result()

    monkeypatch.setattr("app.research.evaluator.BacktestEngine.run", fake_run)
    evaluator = BacktestResearchEvaluator("BTC/USDT", {})
    result = evaluator(
        ParameterSet.from_mapping({"min_score": Decimal("95")})
    )

    assert result.summary.total_return_percent == Decimal("5")
    assert seen[0][0].min_score == Decimal("95")
    assert seen[0][1] == "BTC/USDT"


def test_walk_forward_research_evaluator_aggregates_oos_windows(monkeypatch) -> None:
    fake = WalkForwardResult(
        windows=(WalkForwardWindow(0, 10, 10, 15), WalkForwardWindow(5, 15, 15, 20)),
        results=(_backtest_result("4", drawdown="2"), _backtest_result("6", drawdown="3")),
    )

    def fake_run(self, symbol, candles, train_size, test_size, step=None):
        return fake

    monkeypatch.setattr("app.research.evaluator.WalkForwardRunner.run", fake_run)
    evaluator = WalkForwardResearchEvaluator(
        symbol="BTC/USDT",
        candles_by_timeframe={},
        train_size=10,
        test_size=5,
    )
    result = evaluator(ParameterSet())

    assert result.summary.window_count == 2
    assert result.summary.total_return_percent == Decimal("5")
    assert result.summary.max_drawdown_percent == Decimal("3")
    assert len(result.windows) == 2


def test_portfolio_research_evaluator_uses_same_controlled_rules(monkeypatch) -> None:
    seen = []
    portfolio_result = PortfolioBacktestResult(
        results={"BTC/USDT": _backtest_result()},
        initial_equity=Decimal("10000"),
        final_equity=Decimal("10500"),
        total_return_percent=Decimal("5"),
        max_drawdown_percent=Decimal("2"),
        total_trades=0,
        equity_curve=(Decimal("10000"), Decimal("10500")),
    )

    def fake_run(self, candles):
        seen.append((self.rules, candles))
        return portfolio_result

    monkeypatch.setattr("app.research.evaluator.PortfolioBacktestEngine.run", fake_run)
    evaluator = PortfolioResearchEvaluator(candles_by_symbol={})
    result = evaluator(
        ParameterSet.from_mapping({"min_confidence": Decimal("96")})
    )

    assert result.summary.total_return_percent == Decimal("5")
    assert seen[0][0].min_confidence == Decimal("96")
