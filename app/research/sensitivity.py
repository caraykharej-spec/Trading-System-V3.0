from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import ExperimentResult, ParameterValue


@dataclass(frozen=True)
class SensitivityPoint:
    value: ParameterValue
    trials: int
    mean_objective: Decimal
    best_objective: Decimal
    worst_objective: Decimal


@dataclass(frozen=True)
class ParameterSensitivity:
    parameter_name: str
    points: tuple[SensitivityPoint, ...]
    mean_objective_spread: Decimal


@dataclass(frozen=True)
class SensitivityReport:
    parameters: tuple[ParameterSensitivity, ...]


def analyze_parameter_sensitivity(result: ExperimentResult) -> SensitivityReport:
    reports: list[ParameterSensitivity] = []
    feasible = [trial for trial in result.trials if trial.feasible]
    for definition in result.spec.parameter_space.definitions:
        points: list[SensitivityPoint] = []
        means: list[Decimal] = []
        for value in definition.values:
            matching = [
                trial.selection_objective
                for trial in feasible
                if trial.parameters.get(definition.name) == value
            ]
            if not matching:
                continue
            mean = sum(matching, Decimal("0")) / Decimal(len(matching))
            means.append(mean)
            points.append(
                SensitivityPoint(
                    value=value,
                    trials=len(matching),
                    mean_objective=mean,
                    best_objective=max(matching),
                    worst_objective=min(matching),
                )
            )
        spread = max(means) - min(means) if means else Decimal("0")
        reports.append(
            ParameterSensitivity(
                parameter_name=definition.name,
                points=tuple(points),
                mean_objective_spread=spread,
            )
        )
    return SensitivityReport(parameters=tuple(reports))
