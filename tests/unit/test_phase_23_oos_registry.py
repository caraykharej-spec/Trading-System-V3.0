from __future__ import annotations

import sqlite3
from decimal import Decimal

from app.backtest.models import BacktestResult
from app.research.engine import ResearchRunner
from app.research.models import (
    DatasetRole,
    ExperimentSpec,
    ParameterSet,
    ParameterSpec,
    ResearchConstraints,
)
from app.research.parameter_space import ParameterSpace
from app.research.registry import SQLiteResearchRegistry


def _result(value: Decimal) -> BacktestResult:
    return BacktestResult(
        initial_equity=Decimal("10000"),
        final_equity=Decimal("10000") + value,
        trades=(),
        rejected_signals=0,
        open_positions_at_end=0,
        max_drawdown_percent=Decimal("1"),
        win_rate_percent=Decimal("50"),
        profit_factor=Decimal("2"),
        total_return_percent=value,
        max_concurrent_positions=0,
    )


def test_sqlite_registry_persists_sealed_oos_failure() -> None:
    connection = sqlite3.connect(":memory:")
    registry = SQLiteResearchRegistry(connection)

    def evaluator(parameters: ParameterSet, seed: int, role: DatasetRole) -> BacktestResult:
        del seed
        if role is DatasetRole.OOS:
            raise ValueError("simulated sealed OOS failure")
        return _result(Decimal(parameters.get("threshold")))

    result = ResearchRunner(evaluator, registry).run(
        ExperimentSpec(
            experiment_id="oos-failure",
            strategy_version="strategy-v1",
            data_version="data-v1",
            constraints=ResearchConstraints(min_trades=0),
        ),
        ParameterSpace((ParameterSpec("threshold", (1, 2)),)),
    )

    assert result.oos_error == "OOS_VALUEERROR"
    stored = registry.get_summary("oos-failure")
    assert stored is not None
    assert stored.oos_objective is None
    assert stored.oos_error == "OOS_VALUEERROR"
