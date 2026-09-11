from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Iterable

from .models import StrategyValidationPolicy
from .qualification import StrategyValidationEvidence


class CalibrationStatus(str, Enum):
    CALIBRATED = "CALIBRATED"
    HOLD = "HOLD"


class ThresholdDirection(str, Enum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"


@dataclass(frozen=True)
class CalibrationObservation:
    """One independent historical validation snapshot used for calibration."""

    sample_id: str
    as_of: datetime
    oos_return_percent: Decimal | None = None
    oos_profit_factor: Decimal | None = None
    oos_drawdown_percent: Decimal | None = None
    profitable_walk_forward_ratio: Decimal | None = None
    monte_carlo_median_return_percent: Decimal | None = None
    monte_carlo_worst_drawdown_percent: Decimal | None = None
    cost_stress_degradation_percent: Decimal | None = None
    parameter_normalized_spread: Decimal | None = None
    feasible_trial_ratio: Decimal | None = None
    forward_hit_rate_percent: Decimal | None = None
    forward_mean_return_percent: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.sample_id.strip():
            raise ValueError("calibration sample_id cannot be blank")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("calibration as_of must be timezone-aware")

        non_negative = (
            self.oos_profit_factor,
            self.oos_drawdown_percent,
            self.monte_carlo_worst_drawdown_percent,
            self.cost_stress_degradation_percent,
            self.parameter_normalized_spread,
        )
        if any(value is not None and value < 0 for value in non_negative):
            raise ValueError("calibration loss/risk metrics must be non-negative")

        ratios = (self.profitable_walk_forward_ratio, self.feasible_trial_ratio)
        if any(value is not None and not Decimal("0") <= value <= Decimal("1") for value in ratios):
            raise ValueError("calibration ratios must be in [0, 1]")

        hit_rate = self.forward_hit_rate_percent
        if hit_rate is not None and not Decimal("0") <= hit_rate <= Decimal("100"):
            raise ValueError("forward_hit_rate_percent must be in [0, 100]")

    @classmethod
    def from_evidence(
        cls,
        sample_id: str,
        as_of: datetime,
        evidence: StrategyValidationEvidence,
    ) -> CalibrationObservation:
        walk_forward_ratio: Decimal | None = None
        if evidence.walk_forward is not None and evidence.walk_forward.results:
            results = evidence.walk_forward.results
            profitable = sum(1 for item in results if item.total_return_percent > 0)
            walk_forward_ratio = Decimal(profitable) / Decimal(len(results))

        stability_spread: Decimal | None = None
        feasible_trial_ratio: Decimal | None = None
        if evidence.parameter_stability is not None and evidence.parameter_stability.items:
            stability_spread = evidence.parameter_stability.max_normalized_spread
            feasible_trial_ratio = evidence.parameter_stability.feasible_trial_ratio

        cost_degradation: Decimal | None = None
        if evidence.cost_stress is not None and evidence.cost_stress.outcomes:
            cost_degradation = evidence.cost_stress.worst_return_degradation_percent

        monte_carlo = evidence.monte_carlo
        monte_carlo_median: Decimal | None = None
        monte_carlo_drawdown: Decimal | None = None
        if monte_carlo is not None and monte_carlo.simulations > 0:
            monte_carlo_median = monte_carlo.median_return_percent
            monte_carlo_drawdown = monte_carlo.worst_max_drawdown_percent

        forward_hit_rate: Decimal | None = None
        forward_mean_return: Decimal | None = None
        if evidence.forward is not None and evidence.forward.resolved_observations > 0:
            forward_hit_rate = evidence.forward.hit_rate_percent
            forward_mean_return = evidence.forward.mean_return_percent

        holdout = evidence.holdout
        return cls(
            sample_id=sample_id,
            as_of=as_of,
            oos_return_percent=holdout.total_return_percent if holdout is not None else None,
            oos_profit_factor=holdout.profit_factor if holdout is not None else None,
            oos_drawdown_percent=(
                holdout.max_drawdown_percent if holdout is not None else None
            ),
            profitable_walk_forward_ratio=walk_forward_ratio,
            monte_carlo_median_return_percent=monte_carlo_median,
            monte_carlo_worst_drawdown_percent=monte_carlo_drawdown,
            cost_stress_degradation_percent=cost_degradation,
            parameter_normalized_spread=stability_spread,
            feasible_trial_ratio=feasible_trial_ratio,
            forward_hit_rate_percent=forward_hit_rate,
            forward_mean_return_percent=forward_mean_return,
        )


@dataclass(frozen=True)
class ThresholdCalibrationConfig:
    minimum_samples: int = 20
    minimum_metric_samples: int = 20
    lower_quantile: Decimal = Decimal("0.25")
    upper_quantile: Decimal = Decimal("0.75")

    def __post_init__(self) -> None:
        if self.minimum_samples < 1 or self.minimum_metric_samples < 1:
            raise ValueError("calibration sample minimums must be positive")
        if not Decimal("0") <= self.lower_quantile <= Decimal("0.50"):
            raise ValueError("lower_quantile must be in [0, 0.50]")
        if not Decimal("0.50") <= self.upper_quantile <= Decimal("1"):
            raise ValueError("upper_quantile must be in [0.50, 1]")
        if self.lower_quantile >= self.upper_quantile:
            raise ValueError("lower_quantile must be less than upper_quantile")


@dataclass(frozen=True)
class CalibratedThreshold:
    name: str
    direction: ThresholdDirection
    baseline_value: Decimal
    empirical_value: Decimal
    applied_value: Decimal
    sample_count: int

    @property
    def tightened(self) -> bool:
        if self.direction is ThresholdDirection.HIGHER_IS_BETTER:
            return self.applied_value > self.baseline_value
        return self.applied_value < self.baseline_value


@dataclass(frozen=True)
class ThresholdCalibrationReport:
    status: CalibrationStatus
    source_sample_count: int
    eligible_sample_count: int
    dataset_fingerprint: str
    thresholds: tuple[CalibratedThreshold, ...]
    reasons: tuple[str, ...]
    policy: StrategyValidationPolicy | None

    @property
    def calibrated(self) -> bool:
        return self.status is CalibrationStatus.CALIBRATED and self.policy is not None

    def require_policy(self) -> StrategyValidationPolicy:
        if self.policy is None or self.status is not CalibrationStatus.CALIBRATED:
            raise ValueError("calibration report does not contain an approved policy")
        return self.policy


class ThresholdCalibrator:
    """Derive conservative validation thresholds from independent historical evidence.

    Empirical calibration may tighten Phase 38 thresholds but never loosen the
    supplied baseline guardrails. Candidate evidence is intentionally not accepted
    by this object; callers must supply a separate historical calibration cohort.
    """

    def __init__(
        self,
        baseline: StrategyValidationPolicy | None = None,
        config: ThresholdCalibrationConfig | None = None,
    ) -> None:
        self.baseline = baseline or StrategyValidationPolicy()
        self.config = config or ThresholdCalibrationConfig()

    def calibrate(
        self,
        observations: Iterable[CalibrationObservation],
        *,
        cutoff: datetime | None = None,
    ) -> ThresholdCalibrationReport:
        source = tuple(observations)
        self._validate_unique_ids(source)
        if cutoff is not None and (cutoff.tzinfo is None or cutoff.utcoffset() is None):
            raise ValueError("calibration cutoff must be timezone-aware")

        eligible = tuple(
            item for item in source if cutoff is None or item.as_of < cutoff
        )
        fingerprint = _dataset_fingerprint(eligible)
        reasons: list[str] = []
        if len(eligible) < self.config.minimum_samples:
            reasons.append(
                "insufficient_calibration_cohort:"
                f"{len(eligible)}<{self.config.minimum_samples}"
            )

        metric_inputs = (
            (
                "min_oos_return_percent",
                ThresholdDirection.HIGHER_IS_BETTER,
                self.baseline.min_oos_return_percent,
                _present(item.oos_return_percent for item in eligible),
                self.config.lower_quantile,
            ),
            (
                "min_oos_profit_factor",
                ThresholdDirection.HIGHER_IS_BETTER,
                self.baseline.min_oos_profit_factor,
                _present(item.oos_profit_factor for item in eligible),
                self.config.lower_quantile,
            ),
            (
                "max_oos_drawdown_percent",
                ThresholdDirection.LOWER_IS_BETTER,
                self.baseline.max_oos_drawdown_percent,
                _present(item.oos_drawdown_percent for item in eligible),
                self.config.upper_quantile,
            ),
            (
                "min_profitable_walk_forward_ratio",
                ThresholdDirection.HIGHER_IS_BETTER,
                self.baseline.min_profitable_walk_forward_ratio,
                _present(item.profitable_walk_forward_ratio for item in eligible),
                self.config.lower_quantile,
            ),
            (
                "min_monte_carlo_median_return_percent",
                ThresholdDirection.HIGHER_IS_BETTER,
                self.baseline.min_monte_carlo_median_return_percent,
                _present(item.monte_carlo_median_return_percent for item in eligible),
                self.config.lower_quantile,
            ),
            (
                "max_monte_carlo_worst_drawdown_percent",
                ThresholdDirection.LOWER_IS_BETTER,
                self.baseline.max_monte_carlo_worst_drawdown_percent,
                _present(item.monte_carlo_worst_drawdown_percent for item in eligible),
                self.config.upper_quantile,
            ),
            (
                "max_cost_stress_degradation_percent",
                ThresholdDirection.LOWER_IS_BETTER,
                self.baseline.max_cost_stress_degradation_percent,
                _present(item.cost_stress_degradation_percent for item in eligible),
                self.config.upper_quantile,
            ),
            (
                "max_parameter_normalized_spread",
                ThresholdDirection.LOWER_IS_BETTER,
                self.baseline.max_parameter_normalized_spread,
                _present(item.parameter_normalized_spread for item in eligible),
                self.config.upper_quantile,
            ),
            (
                "min_feasible_trial_ratio",
                ThresholdDirection.HIGHER_IS_BETTER,
                self.baseline.min_feasible_trial_ratio,
                _present(item.feasible_trial_ratio for item in eligible),
                self.config.lower_quantile,
            ),
            (
                "min_forward_hit_rate_percent",
                ThresholdDirection.HIGHER_IS_BETTER,
                self.baseline.min_forward_hit_rate_percent,
                _present(item.forward_hit_rate_percent for item in eligible),
                self.config.lower_quantile,
            ),
            (
                "min_forward_mean_return_percent",
                ThresholdDirection.HIGHER_IS_BETTER,
                self.baseline.min_forward_mean_return_percent,
                _present(item.forward_mean_return_percent for item in eligible),
                self.config.lower_quantile,
            ),
        )

        thresholds: list[CalibratedThreshold] = []
        for name, direction, baseline_value, values, quantile in metric_inputs:
            threshold = self._calibrate_metric(
                name=name,
                direction=direction,
                baseline_value=baseline_value,
                values=values,
                quantile=quantile,
            )
            if threshold is None:
                reasons.append(
                    f"insufficient_metric_samples:{name}:"
                    f"{len(values)}<{self.config.minimum_metric_samples}"
                )
            else:
                thresholds.append(threshold)

        if reasons:
            return ThresholdCalibrationReport(
                status=CalibrationStatus.HOLD,
                source_sample_count=len(source),
                eligible_sample_count=len(eligible),
                dataset_fingerprint=fingerprint,
                thresholds=tuple(thresholds),
                reasons=tuple(reasons),
                policy=None,
            )

        applied = {item.name: item.applied_value for item in thresholds}
        policy = StrategyValidationPolicy(
            min_oos_trades=self.baseline.min_oos_trades,
            min_oos_return_percent=applied["min_oos_return_percent"],
            min_oos_profit_factor=applied["min_oos_profit_factor"],
            max_oos_drawdown_percent=applied["max_oos_drawdown_percent"],
            min_walk_forward_windows=self.baseline.min_walk_forward_windows,
            min_profitable_walk_forward_ratio=applied[
                "min_profitable_walk_forward_ratio"
            ],
            min_monte_carlo_median_return_percent=applied[
                "min_monte_carlo_median_return_percent"
            ],
            max_monte_carlo_worst_drawdown_percent=applied[
                "max_monte_carlo_worst_drawdown_percent"
            ],
            max_cost_stress_degradation_percent=applied[
                "max_cost_stress_degradation_percent"
            ],
            max_parameter_normalized_spread=applied[
                "max_parameter_normalized_spread"
            ],
            min_feasible_trial_ratio=applied["min_feasible_trial_ratio"],
            min_regime_trade_count=self.baseline.min_regime_trade_count,
            min_qualified_regimes=self.baseline.min_qualified_regimes,
            min_forward_observations=self.baseline.min_forward_observations,
            min_forward_hit_rate_percent=applied["min_forward_hit_rate_percent"],
            min_forward_mean_return_percent=applied[
                "min_forward_mean_return_percent"
            ],
        )
        return ThresholdCalibrationReport(
            status=CalibrationStatus.CALIBRATED,
            source_sample_count=len(source),
            eligible_sample_count=len(eligible),
            dataset_fingerprint=fingerprint,
            thresholds=tuple(thresholds),
            reasons=(),
            policy=policy,
        )

    def _calibrate_metric(
        self,
        *,
        name: str,
        direction: ThresholdDirection,
        baseline_value: Decimal,
        values: list[Decimal],
        quantile: Decimal,
    ) -> CalibratedThreshold | None:
        if len(values) < self.config.minimum_metric_samples:
            return None
        empirical = _quantile(values, quantile)
        if direction is ThresholdDirection.HIGHER_IS_BETTER:
            applied = max(baseline_value, empirical)
        else:
            applied = min(baseline_value, empirical)
        return CalibratedThreshold(
            name=name,
            direction=direction,
            baseline_value=baseline_value,
            empirical_value=empirical,
            applied_value=applied,
            sample_count=len(values),
        )

    @staticmethod
    def _validate_unique_ids(observations: tuple[CalibrationObservation, ...]) -> None:
        seen: set[str] = set()
        for item in observations:
            if item.sample_id in seen:
                raise ValueError(f"duplicate calibration sample_id: {item.sample_id}")
            seen.add(item.sample_id)


def _present(values: Iterable[Decimal | None]) -> list[Decimal]:
    return [value for value in values if value is not None]


def _quantile(values: list[Decimal], quantile: Decimal) -> Decimal:
    if not values:
        raise ValueError("quantile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * quantile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - Decimal(lower_index)
    lower = ordered[lower_index]
    upper = ordered[upper_index]
    return lower + (upper - lower) * fraction


def _dataset_fingerprint(observations: tuple[CalibrationObservation, ...]) -> str:
    rows: list[dict[str, str | None]] = []
    for item in sorted(observations, key=lambda value: (value.sample_id, value.as_of)):
        rows.append(
            {
                "sample_id": item.sample_id,
                "as_of": item.as_of.isoformat(),
                "oos_return_percent": _decimal_text(item.oos_return_percent),
                "oos_profit_factor": _decimal_text(item.oos_profit_factor),
                "oos_drawdown_percent": _decimal_text(item.oos_drawdown_percent),
                "profitable_walk_forward_ratio": _decimal_text(
                    item.profitable_walk_forward_ratio
                ),
                "monte_carlo_median_return_percent": _decimal_text(
                    item.monte_carlo_median_return_percent
                ),
                "monte_carlo_worst_drawdown_percent": _decimal_text(
                    item.monte_carlo_worst_drawdown_percent
                ),
                "cost_stress_degradation_percent": _decimal_text(
                    item.cost_stress_degradation_percent
                ),
                "parameter_normalized_spread": _decimal_text(
                    item.parameter_normalized_spread
                ),
                "feasible_trial_ratio": _decimal_text(item.feasible_trial_ratio),
                "forward_hit_rate_percent": _decimal_text(
                    item.forward_hit_rate_percent
                ),
                "forward_mean_return_percent": _decimal_text(
                    item.forward_mean_return_percent
                ),
            }
        )
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
