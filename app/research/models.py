from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
from typing import TypeAlias


ParameterValue: TypeAlias = Decimal | int | bool | str


class SearchMethod(str, Enum):
    GRID = "GRID"
    RANDOM = "RANDOM"


class ObjectiveMetric(str, Enum):
    TOTAL_RETURN_PERCENT = "TOTAL_RETURN_PERCENT"
    WIN_RATE_PERCENT = "WIN_RATE_PERCENT"
    RETURN_DRAWDOWN_RATIO = "RETURN_DRAWDOWN_RATIO"


class ParameterRole(str, Enum):
    STRATEGY_RULE = "STRATEGY_RULE"


def parameter_value_json(value: ParameterValue) -> dict[str, str | int | bool]:
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal research parameters must be finite")
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, int):
        return {"type": "int", "value": value}
    return {"type": "str", "value": value}


@dataclass(frozen=True)
class ParameterDefinition:
    name: str
    values: tuple[ParameterValue, ...]
    role: ParameterRole = ParameterRole.STRATEGY_RULE

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("parameter name cannot be empty")
        if not self.values:
            raise ValueError(f"parameter {self.name} requires at least one value")
        encoded = [json.dumps(parameter_value_json(value), sort_keys=True) for value in self.values]
        if len(encoded) != len(set(encoded)):
            raise ValueError(f"parameter {self.name} contains duplicate values")


@dataclass(frozen=True)
class ParameterSpace:
    definitions: tuple[ParameterDefinition, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.definitions, key=lambda item: item.name))
        names = [item.name for item in ordered]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        object.__setattr__(self, "definitions", ordered)

    @property
    def combination_count(self) -> int:
        total = 1
        for definition in self.definitions:
            total *= len(definition.values)
        return total


@dataclass(frozen=True)
class ParameterSet:
    values: tuple[tuple[str, ParameterValue], ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.values, key=lambda item: item[0]))
        names = [name for name, _ in ordered]
        if len(names) != len(set(names)):
            raise ValueError("parameter set contains duplicate names")
        object.__setattr__(self, "values", ordered)

    @classmethod
    def from_mapping(cls, values: dict[str, ParameterValue]) -> ParameterSet:
        return cls(tuple(values.items()))

    def as_dict(self) -> dict[str, ParameterValue]:
        return dict(self.values)

    def get(self, name: str) -> ParameterValue | None:
        return self.as_dict().get(name)

    @property
    def stable_key(self) -> str:
        payload = [
            {"name": name, "value": parameter_value_json(value)}
            for name, value in self.values
        ]
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DatasetManifest:
    training_fingerprint: str
    validation_fingerprint: str | None = None
    holdout_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.training_fingerprint.strip():
            raise ValueError("training_fingerprint cannot be empty")
        for value in (self.validation_fingerprint, self.holdout_fingerprint):
            if value is not None and not value.strip():
                raise ValueError("dataset fingerprints cannot be blank")


@dataclass(frozen=True)
class ResearchConstraints:
    min_trades: int = 0
    max_drawdown_percent: Decimal | None = None
    min_profit_factor: Decimal | None = None
    min_oos_windows: int = 0
    max_validation_degradation_percent: Decimal | None = None

    def __post_init__(self) -> None:
        if self.min_trades < 0 or self.min_oos_windows < 0:
            raise ValueError("minimum counts must be non-negative")
        if self.max_drawdown_percent is not None and self.max_drawdown_percent < 0:
            raise ValueError("max_drawdown_percent must be non-negative")
        if self.min_profit_factor is not None and self.min_profit_factor < 0:
            raise ValueError("min_profit_factor must be non-negative")
        degradation = self.max_validation_degradation_percent
        if degradation is not None and not Decimal("0") <= degradation <= Decimal("100"):
            raise ValueError("max_validation_degradation_percent must be in [0, 100]")


@dataclass(frozen=True)
class EvaluationSummary:
    total_return_percent: Decimal
    max_drawdown_percent: Decimal
    win_rate_percent: Decimal
    profit_factor: Decimal | None
    trade_count: int
    rejected_signals: int
    window_count: int = 0


@dataclass(frozen=True)
class ResearchEvaluation:
    summary: EvaluationSummary
    windows: tuple[EvaluationSummary, ...] = ()


@dataclass(frozen=True)
class ExperimentSpec:
    name: str
    strategy_version: str
    datasets: DatasetManifest
    parameter_space: ParameterSpace
    objective: ObjectiveMetric = ObjectiveMetric.RETURN_DRAWDOWN_RATIO
    search_method: SearchMethod = SearchMethod.GRID
    seed: int = 42
    max_trials: int = 100
    constraints: ResearchConstraints = field(default_factory=ResearchConstraints)

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.strategy_version.strip():
            raise ValueError("experiment name and strategy_version are required")
        if self.max_trials <= 0:
            raise ValueError("max_trials must be positive")

    @property
    def experiment_id(self) -> str:
        definitions = [
            {
                "name": definition.name,
                "role": definition.role.value,
                "values": [parameter_value_json(value) for value in definition.values],
            }
            for definition in self.parameter_space.definitions
        ]
        payload: dict[str, object] = {
            "framework": "phase-23-v1",
            "name": self.name,
            "strategy_version": self.strategy_version,
            "datasets": {
                "training": self.datasets.training_fingerprint,
                "validation": self.datasets.validation_fingerprint,
                "holdout": self.datasets.holdout_fingerprint,
            },
            "parameter_space": definitions,
            "objective": self.objective.value,
            "search_method": self.search_method.value,
            "seed": self.seed,
            "max_trials": self.max_trials,
            "constraints": {
                "min_trades": self.constraints.min_trades,
                "max_drawdown_percent": (
                    str(self.constraints.max_drawdown_percent)
                    if self.constraints.max_drawdown_percent is not None
                    else None
                ),
                "min_profit_factor": (
                    str(self.constraints.min_profit_factor)
                    if self.constraints.min_profit_factor is not None
                    else None
                ),
                "min_oos_windows": self.constraints.min_oos_windows,
                "max_validation_degradation_percent": (
                    str(self.constraints.max_validation_degradation_percent)
                    if self.constraints.max_validation_degradation_percent is not None
                    else None
                ),
            },
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TrialResult:
    trial_id: str
    parameters: ParameterSet
    training: ResearchEvaluation
    validation: ResearchEvaluation | None
    training_objective: Decimal
    selection_objective: Decimal
    validation_degradation_percent: Decimal | None
    feasible: bool
    violations: tuple[str, ...]

    @property
    def selection_summary(self) -> EvaluationSummary:
        return self.validation.summary if self.validation is not None else self.training.summary


@dataclass(frozen=True)
class ExperimentResult:
    spec: ExperimentSpec
    trials: tuple[TrialResult, ...]
    best_trial: TrialResult | None
    created_at: datetime

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
