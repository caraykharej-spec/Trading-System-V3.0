from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Protocol

from .models import (
    EvaluationSummary,
    ExperimentResult,
    ParameterValue,
    ResearchEvaluation,
    parameter_value_json,
)


@dataclass(frozen=True)
class StoredExperiment:
    experiment_id: str
    name: str
    strategy_version: str
    created_at: str
    payload_json: str


class ExperimentRegistry(Protocol):
    def save(self, result: ExperimentResult) -> bool:
        ...

    def get(self, experiment_id: str) -> StoredExperiment | None:
        ...

    def list_all(self) -> list[StoredExperiment]:
        ...


def _parameter_payload(
    values: tuple[tuple[str, ParameterValue], ...],
) -> list[dict[str, object]]:
    return [
        {"name": name, "value": parameter_value_json(value)}
        for name, value in values
    ]


def _summary_payload(summary: EvaluationSummary) -> dict[str, object]:
    return {
        "total_return_percent": str(summary.total_return_percent),
        "max_drawdown_percent": str(summary.max_drawdown_percent),
        "win_rate_percent": str(summary.win_rate_percent),
        "profit_factor": (
            str(summary.profit_factor) if summary.profit_factor is not None else None
        ),
        "trade_count": summary.trade_count,
        "rejected_signals": summary.rejected_signals,
        "window_count": summary.window_count,
    }


def _evaluation_payload(evaluation: ResearchEvaluation) -> dict[str, object]:
    return {
        "summary": _summary_payload(evaluation.summary),
        "windows": [_summary_payload(window) for window in evaluation.windows],
    }


def serialize_experiment(result: ExperimentResult) -> str:
    spec = result.spec
    constraints = spec.constraints
    payload: dict[str, object] = {
        "experiment_id": spec.experiment_id,
        "name": spec.name,
        "strategy_version": spec.strategy_version,
        "datasets": {
            "training": spec.datasets.training_fingerprint,
            "validation": spec.datasets.validation_fingerprint,
            "holdout": spec.datasets.holdout_fingerprint,
        },
        "objective": spec.objective.value,
        "search_method": spec.search_method.value,
        "seed": spec.seed,
        "max_trials": spec.max_trials,
        "constraints": {
            "min_trades": constraints.min_trades,
            "max_drawdown_percent": (
                str(constraints.max_drawdown_percent)
                if constraints.max_drawdown_percent is not None
                else None
            ),
            "min_profit_factor": (
                str(constraints.min_profit_factor)
                if constraints.min_profit_factor is not None
                else None
            ),
            "min_oos_windows": constraints.min_oos_windows,
            "max_validation_degradation_percent": (
                str(constraints.max_validation_degradation_percent)
                if constraints.max_validation_degradation_percent is not None
                else None
            ),
        },
        "parameters": [
            {
                "name": definition.name,
                "role": definition.role.value,
                "values": [parameter_value_json(value) for value in definition.values],
            }
            for definition in spec.parameter_space.definitions
        ],
        "trials": [
            {
                "trial_id": trial.trial_id,
                "parameters": _parameter_payload(trial.parameters.values),
                "training": _evaluation_payload(trial.training),
                "validation": (
                    _evaluation_payload(trial.validation)
                    if trial.validation is not None
                    else None
                ),
                "training_objective": str(trial.training_objective),
                "selection_objective": str(trial.selection_objective),
                "validation_degradation_percent": (
                    str(trial.validation_degradation_percent)
                    if trial.validation_degradation_percent is not None
                    else None
                ),
                "feasible": trial.feasible,
                "violations": list(trial.violations),
            }
            for trial in result.trials
        ],
        "best_trial_id": result.best_trial.trial_id if result.best_trial is not None else None,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class InMemoryExperimentRegistry:
    def __init__(self) -> None:
        self._rows: dict[str, StoredExperiment] = {}

    def save(self, result: ExperimentResult) -> bool:
        row = _stored(result)
        existing = self._rows.get(row.experiment_id)
        if existing is not None:
            if existing.payload_json != row.payload_json:
                raise RuntimeError("experiment id conflict with different result payload")
            return False
        self._rows[row.experiment_id] = row
        return True

    def get(self, experiment_id: str) -> StoredExperiment | None:
        return self._rows.get(experiment_id)

    def list_all(self) -> list[StoredExperiment]:
        return sorted(self._rows.values(), key=lambda row: (row.created_at, row.experiment_id))


class SQLiteExperimentRegistry:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_experiments (
                experiment_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_research_experiments_created_at
                ON research_experiments(created_at);
            """
        )
        self.connection.commit()

    def save(self, result: ExperimentResult) -> bool:
        row = _stored(result)
        existing = self.get(row.experiment_id)
        if existing is not None:
            if existing.payload_json != row.payload_json:
                raise RuntimeError("experiment id conflict with different result payload")
            return False
        self.connection.execute(
            """
            INSERT INTO research_experiments(
                experiment_id, name, strategy_version, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                row.experiment_id,
                row.name,
                row.strategy_version,
                row.created_at,
                row.payload_json,
            ),
        )
        self.connection.commit()
        return True

    def get(self, experiment_id: str) -> StoredExperiment | None:
        row = self.connection.execute(
            """
            SELECT experiment_id, name, strategy_version, created_at, payload_json
            FROM research_experiments WHERE experiment_id = ?
            """,
            (experiment_id,),
        ).fetchone()
        if row is None:
            return None
        return StoredExperiment(
            experiment_id=str(row[0]),
            name=str(row[1]),
            strategy_version=str(row[2]),
            created_at=str(row[3]),
            payload_json=str(row[4]),
        )

    def list_all(self) -> list[StoredExperiment]:
        rows = self.connection.execute(
            """
            SELECT experiment_id, name, strategy_version, created_at, payload_json
            FROM research_experiments
            ORDER BY created_at, experiment_id
            """
        ).fetchall()
        return [
            StoredExperiment(
                experiment_id=str(row[0]),
                name=str(row[1]),
                strategy_version=str(row[2]),
                created_at=str(row[3]),
                payload_json=str(row[4]),
            )
            for row in rows
        ]


def _stored(result: ExperimentResult) -> StoredExperiment:
    return StoredExperiment(
        experiment_id=result.spec.experiment_id,
        name=result.spec.name,
        strategy_version=result.spec.strategy_version,
        created_at=result.created_at.isoformat(),
        payload_json=serialize_experiment(result),
    )
