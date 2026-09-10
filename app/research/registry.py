from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from .models import ExperimentResult, ParameterSet


@dataclass(frozen=True)
class StoredExperiment:
    experiment_id: str
    fingerprint: str
    strategy_version: str
    data_version: str
    best_parameters_json: str | None
    oos_objective: Decimal | None
    trial_count: int


def _parameters_json(parameters: ParameterSet | None) -> str | None:
    if parameters is None:
        return None
    payload = {
        name: {"type": type(value).__name__, "value": str(value)}
        for name, value in parameters.values
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class InMemoryResearchRegistry:
    def __init__(self) -> None:
        self._results: dict[str, ExperimentResult] = {}

    def save(self, result: ExperimentResult) -> bool:
        existing = self._results.get(result.spec.experiment_id)
        if existing is None:
            self._results[result.spec.experiment_id] = result
            return True
        if existing.fingerprint != result.fingerprint:
            raise ValueError("experiment_id already exists with a different fingerprint")
        return False

    def get(self, experiment_id: str) -> ExperimentResult | None:
        return self._results.get(experiment_id)


class SQLiteResearchRegistry:
    """Immutable experiment/trial registry for reproducible research metadata."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_experiments (
                experiment_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                data_version TEXT NOT NULL,
                seed INTEGER NOT NULL,
                search_method TEXT NOT NULL,
                objective_metric TEXT NOT NULL,
                objective_direction TEXT NOT NULL,
                best_parameters_json TEXT,
                oos_objective TEXT,
                trial_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_trials (
                experiment_id TEXT NOT NULL,
                trial_index INTEGER NOT NULL,
                seed INTEGER NOT NULL,
                parameters_json TEXT NOT NULL,
                status TEXT NOT NULL,
                rejection_reason TEXT,
                train_objective TEXT,
                validation_objective TEXT,
                PRIMARY KEY (experiment_id, trial_index),
                FOREIGN KEY (experiment_id) REFERENCES research_experiments(experiment_id)
            );
            CREATE INDEX IF NOT EXISTS idx_research_trials_status
                ON research_trials(experiment_id, status);
            """
        )
        self._connection.commit()

    def save(self, result: ExperimentResult) -> bool:
        experiment_id = result.spec.experiment_id
        row = self._connection.execute(
            "SELECT fingerprint FROM research_experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        if row is not None:
            if str(row[0]) != result.fingerprint:
                raise ValueError("experiment_id already exists with a different fingerprint")
            return False

        best_parameters = (
            result.best_trial.parameters if result.best_trial is not None else None
        )
        try:
            self._connection.execute("BEGIN")
            self._connection.execute(
                """
                INSERT INTO research_experiments (
                    experiment_id, fingerprint, strategy_version, data_version, seed,
                    search_method, objective_metric, objective_direction,
                    best_parameters_json, oos_objective, trial_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    result.fingerprint,
                    result.spec.strategy_version,
                    result.spec.data_version,
                    result.spec.seed,
                    result.spec.search_method.value,
                    result.spec.objective_metric.value,
                    result.spec.objective_direction.value,
                    _parameters_json(best_parameters),
                    str(result.oos_objective) if result.oos_objective is not None else None,
                    len(result.trials),
                ),
            )
            for trial in result.trials:
                self._connection.execute(
                    """
                    INSERT INTO research_trials (
                        experiment_id, trial_index, seed, parameters_json, status,
                        rejection_reason, train_objective, validation_objective
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        experiment_id,
                        trial.index,
                        trial.seed,
                        _parameters_json(trial.parameters),
                        trial.status.value,
                        trial.rejection_reason,
                        str(trial.train_objective) if trial.train_objective is not None else None,
                        (
                            str(trial.validation_objective)
                            if trial.validation_objective is not None
                            else None
                        ),
                    ),
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return True

    def get_summary(self, experiment_id: str) -> StoredExperiment | None:
        row = self._connection.execute(
            """
            SELECT experiment_id, fingerprint, strategy_version, data_version,
                   best_parameters_json, oos_objective, trial_count
            FROM research_experiments WHERE experiment_id = ?
            """,
            (experiment_id,),
        ).fetchone()
        if row is None:
            return None
        return StoredExperiment(
            experiment_id=str(row[0]),
            fingerprint=str(row[1]),
            strategy_version=str(row[2]),
            data_version=str(row[3]),
            best_parameters_json=str(row[4]) if row[4] is not None else None,
            oos_objective=Decimal(str(row[5])) if row[5] is not None else None,
            trial_count=int(row[6]),
        )
