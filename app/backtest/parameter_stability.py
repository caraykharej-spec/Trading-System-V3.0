from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

MAX_PARAMETER_SCENARIOS = 512


class PerturbationMode(str, Enum):
    RELATIVE_PERCENT = "RELATIVE_PERCENT"
    ABSOLUTE = "ABSOLUTE"


@dataclass(frozen=True)
class ParameterSweepSpec:
    name: str
    baseline: Decimal
    perturbations: tuple[Decimal, ...]
    mode: PerturbationMode = PerturbationMode.RELATIVE_PERCENT
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("parameter name must be non-empty")
        values = (self.baseline, *self.perturbations)
        if any(not value.is_finite() for value in values):
            raise ValueError("parameter values and perturbations must be finite")
        if not self.perturbations:
            raise ValueError("perturbations must be non-empty")
        if any(value == 0 for value in self.perturbations):
            raise ValueError("perturbations must exclude zero; baseline is implicit")
        if len(set(self.perturbations)) != len(self.perturbations):
            raise ValueError("perturbations must be unique")
        for bound, label in (
            (self.lower_bound, "lower_bound"),
            (self.upper_bound, "upper_bound"),
        ):
            if bound is not None and not bound.is_finite():
                raise ValueError(f"{label} must be finite")
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValueError("lower_bound must not exceed upper_bound")
        if self.lower_bound is not None and self.baseline < self.lower_bound:
            raise ValueError("baseline is below lower_bound")
        if self.upper_bound is not None and self.baseline > self.upper_bound:
            raise ValueError("baseline is above upper_bound")


@dataclass(frozen=True)
class StabilityThresholds:
    stability_tolerance_percent: Decimal = Decimal("10")
    max_degradation_percent: Decimal = Decimal("20")
    min_stable_fraction: Decimal = Decimal("0.75")
    max_adjacent_cliff_percent: Decimal = Decimal("25")
    max_scenarios: int = MAX_PARAMETER_SCENARIOS

    def __post_init__(self) -> None:
        decimal_values = (
            self.stability_tolerance_percent,
            self.max_degradation_percent,
            self.min_stable_fraction,
            self.max_adjacent_cliff_percent,
        )
        if any(not value.is_finite() for value in decimal_values):
            raise ValueError("stability thresholds must be finite")
        if self.stability_tolerance_percent < 0:
            raise ValueError("stability_tolerance_percent must be non-negative")
        if self.max_degradation_percent < 0:
            raise ValueError("max_degradation_percent must be non-negative")
        if not Decimal("0") <= self.min_stable_fraction <= Decimal("1"):
            raise ValueError("min_stable_fraction must be in [0, 1]")
        if self.max_adjacent_cliff_percent < 0:
            raise ValueError("max_adjacent_cliff_percent must be non-negative")
        if self.max_scenarios < 1 or self.max_scenarios > 10_000:
            raise ValueError("max_scenarios must be in [1, 10000]")


@dataclass(frozen=True)
class SensitivityPoint:
    parameter: str
    value: Decimal
    requested_perturbation: Decimal
    score: Decimal
    absolute_change_percent: Decimal
    degradation_percent: Decimal


@dataclass(frozen=True)
class ParameterStability:
    parameter: str
    points: tuple[SensitivityPoint, ...]
    stable_fraction: Decimal
    worst_degradation_percent: Decimal
    max_adjacent_cliff_percent: Decimal
    passed: bool


@dataclass(frozen=True)
class ParameterStabilityReport:
    baseline_score: Decimal
    parameter_results: tuple[ParameterStability, ...]
    scenario_count: int
    passed: bool
    evidence_fingerprint: str


def _bounded_value(spec: ParameterSweepSpec, perturbation: Decimal) -> Decimal:
    if spec.mode is PerturbationMode.RELATIVE_PERCENT:
        value = spec.baseline * (Decimal("1") + perturbation / Decimal("100"))
    else:
        value = spec.baseline + perturbation
    if spec.lower_bound is not None:
        value = max(value, spec.lower_bound)
    if spec.upper_bound is not None:
        value = min(value, spec.upper_bound)
    return value


def _scenario_values(spec: ParameterSweepSpec) -> tuple[tuple[Decimal, Decimal], ...]:
    by_value: dict[Decimal, Decimal] = {}
    for perturbation in sorted(spec.perturbations):
        value = _bounded_value(spec, perturbation)
        if value == spec.baseline:
            continue
        by_value.setdefault(value, perturbation)
    return tuple((value, by_value[value]) for value in sorted(by_value))


def _score(
    evaluator: Callable[[Mapping[str, Decimal]], Decimal],
    parameters: Mapping[str, Decimal],
) -> Decimal:
    value = evaluator(dict(parameters))
    if not value.is_finite():
        raise ValueError("evaluator score must be finite")
    return value


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _fingerprint_payload(
    *,
    specs: tuple[ParameterSweepSpec, ...],
    thresholds: StabilityThresholds,
    baseline_score: Decimal,
    parameter_results: tuple[ParameterStability, ...],
    scenario_count: int,
    passed: bool,
) -> str:
    payload = {
        "baseline_score": _decimal_text(baseline_score),
        "passed": passed,
        "scenario_count": scenario_count,
        "thresholds": {
            "stability_tolerance_percent": _decimal_text(
                thresholds.stability_tolerance_percent
            ),
            "max_degradation_percent": _decimal_text(
                thresholds.max_degradation_percent
            ),
            "min_stable_fraction": _decimal_text(thresholds.min_stable_fraction),
            "max_adjacent_cliff_percent": _decimal_text(
                thresholds.max_adjacent_cliff_percent
            ),
            "max_scenarios": thresholds.max_scenarios,
        },
        "parameters": [
            {
                "name": spec.name,
                "baseline": _decimal_text(spec.baseline),
                "mode": spec.mode.value,
                "perturbations": [
                    _decimal_text(value) for value in spec.perturbations
                ],
                "lower_bound": (
                    _decimal_text(spec.lower_bound)
                    if spec.lower_bound is not None
                    else None
                ),
                "upper_bound": (
                    _decimal_text(spec.upper_bound)
                    if spec.upper_bound is not None
                    else None
                ),
            }
            for spec in specs
        ],
        "results": [
            {
                "parameter": result.parameter,
                "stable_fraction": _decimal_text(result.stable_fraction),
                "worst_degradation_percent": _decimal_text(
                    result.worst_degradation_percent
                ),
                "max_adjacent_cliff_percent": _decimal_text(
                    result.max_adjacent_cliff_percent
                ),
                "passed": result.passed,
                "points": [
                    {
                        "value": _decimal_text(point.value),
                        "requested_perturbation": _decimal_text(
                            point.requested_perturbation
                        ),
                        "score": _decimal_text(point.score),
                        "absolute_change_percent": _decimal_text(
                            point.absolute_change_percent
                        ),
                        "degradation_percent": _decimal_text(
                            point.degradation_percent
                        ),
                    }
                    for point in result.points
                ],
            }
            for result in parameter_results
        ],
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def qualify_parameter_stability(
    specs: tuple[ParameterSweepSpec, ...],
    *,
    evaluator: Callable[[Mapping[str, Decimal]], Decimal],
    thresholds: StabilityThresholds = StabilityThresholds(),
) -> ParameterStabilityReport:
    if not specs:
        raise ValueError("at least one parameter sweep is required")
    names = [spec.name for spec in specs]
    if len(set(names)) != len(names):
        raise ValueError("parameter names must be unique")
    canonical_specs = tuple(sorted(specs, key=lambda spec: spec.name))

    baseline_parameters = {spec.name: spec.baseline for spec in canonical_specs}
    baseline_score = _score(evaluator, baseline_parameters)
    if baseline_score <= 0:
        raise ValueError("baseline evaluator score must be positive")

    scenarios = [(spec, _scenario_values(spec)) for spec in canonical_specs]
    scenario_count = 1 + sum(len(values) for _, values in scenarios)
    if scenario_count > thresholds.max_scenarios:
        raise ValueError("parameter sweep exceeds max_scenarios")

    results: list[ParameterStability] = []
    hundred = Decimal("100")
    for spec, values in scenarios:
        points: list[SensitivityPoint] = []
        for value, perturbation in values:
            parameters = dict(baseline_parameters)
            parameters[spec.name] = value
            score = _score(evaluator, parameters)
            change = abs(score - baseline_score) / baseline_score * hundred
            degradation = max(
                Decimal("0"),
                (baseline_score - score) / baseline_score * hundred,
            )
            points.append(
                SensitivityPoint(
                    parameter=spec.name,
                    value=value,
                    requested_perturbation=perturbation,
                    score=score,
                    absolute_change_percent=change,
                    degradation_percent=degradation,
                )
            )

        if not points:
            raise ValueError(
                f"parameter sweep for {spec.name!r} has no distinct bounded scenarios"
            )

        stable_count = sum(
            point.absolute_change_percent <= thresholds.stability_tolerance_percent
            for point in points
        )
        stable_fraction = Decimal(stable_count) / Decimal(len(points))
        worst_degradation = max(
            (point.degradation_percent for point in points),
            default=Decimal("0"),
        )

        ordered_scores = [
            (spec.baseline, baseline_score),
            *((point.value, point.score) for point in points),
        ]
        ordered_scores.sort(key=lambda item: item[0])
        cliffs = [
            abs(right_score - left_score) / baseline_score * hundred
            for (_, left_score), (_, right_score) in zip(
                ordered_scores, ordered_scores[1:]
            )
        ]
        max_cliff = max(cliffs, default=Decimal("0"))

        passed = (
            stable_fraction >= thresholds.min_stable_fraction
            and worst_degradation <= thresholds.max_degradation_percent
            and max_cliff <= thresholds.max_adjacent_cliff_percent
        )
        results.append(
            ParameterStability(
                parameter=spec.name,
                points=tuple(points),
                stable_fraction=stable_fraction,
                worst_degradation_percent=worst_degradation,
                max_adjacent_cliff_percent=max_cliff,
                passed=passed,
            )
        )

    parameter_results = tuple(results)
    passed = all(result.passed for result in parameter_results)
    fingerprint = _fingerprint_payload(
        specs=canonical_specs,
        thresholds=thresholds,
        baseline_score=baseline_score,
        parameter_results=parameter_results,
        scenario_count=scenario_count,
        passed=passed,
    )
    return ParameterStabilityReport(
        baseline_score=baseline_score,
        parameter_results=parameter_results,
        scenario_count=scenario_count,
        passed=passed,
        evidence_fingerprint=fingerprint,
    )
