from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import TypeAlias

from app.backtest.models import BacktestResult

ParameterValue: TypeAlias = Decimal | int | bool | str


class DatasetRole(str, Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    OOS = "OOS"


class SearchMethod(str, Enum):
    GRID = "GRID"
    RANDOM = "RANDOM"


class TrialStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class ObjectiveMetric(str, Enum):
    TOTAL_RETURN_PERCENT = "TOTAL_RETURN_PERCENT"
    FINAL_EQUITY = "FINAL_EQUITY"
    PROFIT_FACTOR = "PROFIT_FACTOR"
    MAX_DRAWDOWN_PERCENT = "MAX_DRAWDOWN_PERCENT"
    WIN_RATE_PERCENT = "WIN_RATE_PERCENT"


class ObjectiveDirection(str, Enum):
    MAXIMIZE = "MAXIMIZE"
    MINIMIZE = "MINIMIZE"


def _value_key(value: ParameterValue) -> tuple[str, str]:
    return type(value).__name__, str(value)


@dataclass(frozen=True)
class ParameterSet:
    values: tuple[tuple[str, ParameterValue], ...]

    def __post_init__(self) -> None:
        names = [name for name, _ in self.values]
        if any(not name.strip() for name in names):
            raise ValueError("parameter names must be non-empty")
        if len(set(names)) != len(names):
            raise ValueError("parameter names must be unique")
        if tuple(sorted(self.values, key=lambda item: item[0])) != self.values:
            raise ValueError("ParameterSet values must be sorted by name")

    @classmethod
    def from_mapping(cls, values: dict[str, ParameterValue]) -> ParameterSet:
        return cls(tuple(sorted(values.items(), key=lambda item: item[0])))

    def as_dict(self) -> dict[str, ParameterValue]:
        return dict(self.values)

    def get(self, name: str) -> ParameterValue:
        for key, value in self.values:
            if key == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    values: tuple[ParameterValue, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("parameter name must be non-empty")
        if not self.values:
            raise ValueError(f"parameter {self.name} must define at least one value")
        keys = [_value_key(value) for value in self.values]
        if len(set(keys)) != len(keys):
            raise ValueError(f"parameter {self.name} contains duplicate values")


@dataclass(frozen=True)
class ResearchConstraints:
    min_trades: int = 1
    max_drawdown_percent: Decimal | None = None
    min_profit_factor: Decimal | None = None
    min_total_return_percent: Decimal | None = None

    def __post_init__(self) -> None:
        if self.min_trades < 0:
            raise ValueError("min_trades must be non-negative")
        if self.max_drawdown_percent is not None and self.max_drawdown_percent < 0:
            raise ValueError("max_drawdown_percent must be non-negative")
        if self.min_profit_factor is not None and self.min_profit_factor < 0:
            raise ValueError("min_profit_factor must be non-negative")


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    strategy_version: str
    data_version: str
    seed: int = 42
    search_method: SearchMethod = SearchMethod.GRID
    max_trials: int = 1000
    objective_metric: ObjectiveMetric = ObjectiveMetric.TOTAL_RETURN_PERCENT
    objective_direction: ObjectiveDirection = ObjectiveDirection.MAXIMIZE
    constraints: ResearchConstraints = ResearchConstraints()

    def __post_init__(self) -> None:
        for label, value in (
            ("experiment_id", self.experiment_id),
            ("strategy_version", self.strategy_version),
            ("data_version", self.data_version),
        ):
            if not value.strip():
                raise ValueError(f"{label} must be non-empty")
        if self.max_trials <= 0:
            raise ValueError("max_trials must be positive")


@dataclass(frozen=True)
class ResearchTrial:
    index: int
    parameters: ParameterSet
    seed: int
    status: TrialStatus
    train_result: BacktestResult | None
    validation_result: BacktestResult | None
    train_objective: Decimal | None
    validation_objective: Decimal | None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class ParameterSensitivity:
    parameter: str
    value: str
    observations: int
    average_validation_objective: Decimal
    best_validation_objective: Decimal


@dataclass(frozen=True)
class ExperimentResult:
    spec: ExperimentSpec
    fingerprint: str
    trials: tuple[ResearchTrial, ...]
    best_trial: ResearchTrial | None
    oos_result: BacktestResult | None
    oos_objective: Decimal | None
    sensitivity: tuple[ParameterSensitivity, ...]
