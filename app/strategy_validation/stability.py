from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.research.models import ExperimentResult
from app.research.sensitivity import analyze_parameter_sensitivity


@dataclass(frozen=True)
class ParameterStabilityItem:
    parameter_name: str
    normalized_spread: Decimal
    stable: bool


@dataclass(frozen=True)
class ParameterStabilityReport:
    feasible_trial_ratio: Decimal
    items: tuple[ParameterStabilityItem, ...]

    @property
    def stable(self) -> bool:
        return bool(self.items) and all(item.stable for item in self.items)

    @property
    def max_normalized_spread(self) -> Decimal:
        return max((item.normalized_spread for item in self.items), default=Decimal("0"))


def analyze_parameter_stability(
    result: ExperimentResult,
    *,
    max_normalized_spread: Decimal,
) -> ParameterStabilityReport:
    if max_normalized_spread < 0:
        raise ValueError("max_normalized_spread must be non-negative")
    feasible = sum(1 for trial in result.trials if trial.feasible)
    feasible_ratio = (
        Decimal(feasible) / Decimal(len(result.trials))
        if result.trials
        else Decimal("0")
    )
    sensitivity = analyze_parameter_sensitivity(result)
    items: list[ParameterStabilityItem] = []
    epsilon = Decimal("0.00000001")

    for parameter in sensitivity.parameters:
        reference = max(
            (abs(point.mean_objective) for point in parameter.points),
            default=Decimal("0"),
        )
        denominator = max(reference, epsilon)
        normalized = parameter.mean_objective_spread / denominator
        items.append(
            ParameterStabilityItem(
                parameter_name=parameter.parameter_name,
                normalized_spread=normalized,
                stable=normalized <= max_normalized_spread,
            )
        )

    return ParameterStabilityReport(
        feasible_trial_ratio=feasible_ratio,
        items=tuple(items),
    )
