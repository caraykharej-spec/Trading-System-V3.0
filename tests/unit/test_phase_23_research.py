from __future__ import annotations

import sqlite3
from collections import Counter
from decimal import Decimal

import pytest

from app.backtest.models import BacktestResult
from app.research.engine import ResearchRunner
from app.research.models import (
    DatasetRole,
    ExperimentSpec,
    ObjectiveMetric,
    ParameterSet,
    ParameterSpec,
    ResearchConstraints,
    SearchMethod,
    TrialStatus,
)
from app.research.parameter_space import ParameterSpace
from app.research.registry import InMemoryResearchRegistry, SQLiteResearchRegistry


def _result(
    value: Decimal,
    *,
    drawdown: Decimal = Decimal("5"),
    profit_factor: Decimal | None = Decimal("2"),
    trades: tuple[object, ...] = (),
) -> BacktestResult:
    # Trade content is irrelevant to these framework tests; only cardinality is used.
    return BacktestResult(
        initial_equity=Decimal("10000"),
        final_equity=Decimal("10000") + value,
        trades=trades,  # type: ignore[arg-type]
        rejected_signals=0,
        open_positions_at_end=0,
        max_drawdown_percent=drawdown,
        win_rate_percent=Decimal("50"),
        profit_factor=profit_factor,
        total_return_percent=value,
        max_concurrent_positions=1,
    )


def _space() -> ParameterSpace:
    return ParameterSpace((ParameterSpec("threshold", (1, 2, 3)),))


def _spec(**kwargs: object) -> ExperimentSpec:
    base: dict[str, object] = {
        "experiment_id": "exp-001",
        "strategy_version": "strategy-v1",
        "data_version": "dataset-v1",
        "constraints": ResearchConstraints(min_trades=0),
    }
    base.update(kwargs)
    return ExperimentSpec(**base)  # type: ignore[arg-type]


def test_parameter_space_grid_is_deterministic_and_never_silently_truncates() -> None:
    space = ParameterSpace(
        (
            ParameterSpec("b", (2, 1)),
            ParameterSpec("a", ("x", "y")),
        )
    )
    first = space.candidates(method=SearchMethod.GRID, seed=7, max_trials=4)
    second = space.candidates(method=SearchMethod.GRID, seed=999, max_trials=4)
    assert first == second
    assert len(first) == 4
    assert first[0].values == (("a", "x"), ("b", 2))
    with pytest.raises(ValueError, match="silently truncate"):
        space.candidates(method=SearchMethod.GRID, seed=7, max_trials=3)


def test_random_search_is_seeded_without_replacement() -> None:
    space = ParameterSpace((ParameterSpec("x", tuple(range(10))),))
    a = space.candidates(method=SearchMethod.RANDOM, seed=123, max_trials=4)
    b = space.candidates(method=SearchMethod.RANDOM, seed=123, max_trials=4)
    c = space.candidates(method=SearchMethod.RANDOM, seed=124, max_trials=4)
    assert a == b
    assert a != c
    assert len(set(a)) == 4


def test_parameter_space_has_cartesian_safety_limit() -> None:
    with pytest.raises(ValueError, match="above safety limit"):
        ParameterSpace(
            (ParameterSpec("x", tuple(range(11))), ParameterSpec("y", tuple(range(10)))),
            max_combinations=100,
        )


def test_research_selects_on_validation_and_evaluates_oos_once() -> None:
    calls: Counter[DatasetRole] = Counter()

    def evaluator(parameters: ParameterSet, seed: int, role: DatasetRole) -> BacktestResult:
        assert seed >= 0
        calls[role] += 1
        x = Decimal(parameters.get("threshold"))
        multiplier = {
            DatasetRole.TRAIN: Decimal("1"),
            DatasetRole.VALIDATION: Decimal("2"),
            DatasetRole.OOS: Decimal("3"),
        }[role]
        return _result(x * multiplier)

    result = ResearchRunner(evaluator).run(_spec(), _space())
    assert result.best_trial is not None
    assert result.best_trial.parameters.get("threshold") == 3
    assert result.best_trial.validation_objective == Decimal("6")
    assert result.oos_objective == Decimal("9")
    assert calls == Counter({DatasetRole.TRAIN: 3, DatasetRole.VALIDATION: 3, DatasetRole.OOS: 1})


def test_constraints_reject_before_validation_and_keep_reason() -> None:
    calls: Counter[DatasetRole] = Counter()

    def evaluator(parameters: ParameterSet, seed: int, role: DatasetRole) -> BacktestResult:
        del seed
        calls[role] += 1
        drawdown = Decimal("20") if parameters.get("threshold") == 1 else Decimal("5")
        return _result(Decimal("1"), drawdown=drawdown)

    spec = _spec(constraints=ResearchConstraints(min_trades=0, max_drawdown_percent=Decimal("10")))
    result = ResearchRunner(evaluator).run(spec, _space())
    rejected = [trial for trial in result.trials if trial.status is TrialStatus.REJECTED]
    assert rejected[0].rejection_reason == "TRAIN_MAX_DRAWDOWN"
    assert calls[DatasetRole.VALIDATION] == 2


def test_undefined_objective_is_rejected_instead_of_fabricated() -> None:
    def evaluator(parameters: ParameterSet, seed: int, role: DatasetRole) -> BacktestResult:
        del parameters, seed, role
        return _result(Decimal("1"), profit_factor=None)

    result = ResearchRunner(evaluator).run(
        _spec(objective_metric=ObjectiveMetric.PROFIT_FACTOR),
        _space(),
    )
    assert result.best_trial is None
    assert all(trial.rejection_reason == "TRAIN_OBJECTIVE_UNDEFINED" for trial in result.trials)
    assert result.oos_result is None


def test_expected_evaluation_error_is_auditable_and_does_not_abort_search() -> None:
    def evaluator(parameters: ParameterSet, seed: int, role: DatasetRole) -> BacktestResult:
        del seed, role
        if parameters.get("threshold") == 2:
            raise ValueError("bad candidate")
        return _result(Decimal(parameters.get("threshold")))

    result = ResearchRunner(evaluator).run(_spec(), _space())
    failed = [trial for trial in result.trials if trial.status is TrialStatus.ERROR]
    assert len(failed) == 1
    assert failed[0].rejection_reason == "EVALUATION_VALUEERROR"
    assert result.best_trial is not None
    assert result.best_trial.parameters.get("threshold") == 3


def test_experiment_fingerprint_and_trial_seeds_are_reproducible() -> None:
    def evaluator(parameters: ParameterSet, seed: int, role: DatasetRole) -> BacktestResult:
        del seed, role
        return _result(Decimal(parameters.get("threshold")))

    first = ResearchRunner(evaluator).run(_spec(), _space())
    second = ResearchRunner(evaluator).run(_spec(), _space())
    assert first.fingerprint == second.fingerprint
    assert [trial.seed for trial in first.trials] == [trial.seed for trial in second.trials]
    changed = ResearchRunner(evaluator).run(_spec(data_version="dataset-v2"), _space())
    assert changed.fingerprint != first.fingerprint


def test_sensitivity_reports_each_parameter_value() -> None:
    def evaluator(parameters: ParameterSet, seed: int, role: DatasetRole) -> BacktestResult:
        del seed
        x = Decimal(parameters.get("threshold"))
        return _result(x if role is not DatasetRole.VALIDATION else x * Decimal("2"))

    result = ResearchRunner(evaluator).run(_spec(), _space())
    assert {(row.parameter, row.value, row.observations) for row in result.sensitivity} == {
        ("threshold", "int:1", 1),
        ("threshold", "int:2", 1),
        ("threshold", "int:3", 1),
    }


def test_in_memory_registry_is_immutable_by_experiment_id() -> None:
    def evaluator(parameters: ParameterSet, seed: int, role: DatasetRole) -> BacktestResult:
        del seed, role
        return _result(Decimal(parameters.get("threshold")))

    registry = InMemoryResearchRegistry()
    runner = ResearchRunner(evaluator, registry)
    first = runner.run(_spec(), _space())
    assert registry.get("exp-001") == first
    assert registry.save(first) is False
    with pytest.raises(ValueError, match="different fingerprint"):
        runner.run(_spec(data_version="dataset-v2"), _space())


def test_sqlite_registry_round_trip_and_idempotency() -> None:
    connection = sqlite3.connect(":memory:")
    registry = SQLiteResearchRegistry(connection)

    def evaluator(parameters: ParameterSet, seed: int, role: DatasetRole) -> BacktestResult:
        del seed, role
        return _result(Decimal(parameters.get("threshold")))

    result = ResearchRunner(evaluator, registry).run(_spec(), _space())
    stored = registry.get_summary("exp-001")
    assert stored is not None
    assert stored.fingerprint == result.fingerprint
    assert stored.trial_count == 3
    assert stored.oos_objective == Decimal("3")
    assert registry.save(result) is False
    assert connection.execute("SELECT COUNT(*) FROM research_trials").fetchone()[0] == 3
