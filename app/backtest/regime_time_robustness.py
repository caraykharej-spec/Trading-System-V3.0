from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

MAX_TIME_SLICES = 2048


@dataclass(frozen=True)
class RegimeTimeSlice:
    slice_id: str
    regime: str
    start_index: int
    end_index: int
    score: Decimal
    sample_count: int = 1

    def __post_init__(self) -> None:
        if not self.slice_id.strip():
            raise ValueError("slice_id must be non-empty")
        if not self.regime.strip():
            raise ValueError("regime must be non-empty")
        if self.start_index < 0:
            raise ValueError("start_index must be non-negative")
        if self.end_index <= self.start_index:
            raise ValueError("end_index must be greater than start_index")
        if not self.score.is_finite():
            raise ValueError("slice score must be finite")
        if self.sample_count < 1:
            raise ValueError("sample_count must be positive")


@dataclass(frozen=True)
class RegimeTimeThresholds:
    min_regime_count: int = 2
    min_time_slice_count: int = 4
    min_slices_per_regime: int = 2
    min_regime_relative_score_percent: Decimal = Decimal("60")
    max_regime_spread_percent: Decimal = Decimal("50")
    weak_slice_floor_percent: Decimal = Decimal("60")
    min_stable_time_fraction: Decimal = Decimal("0.75")
    max_time_degradation_percent: Decimal = Decimal("50")
    max_consecutive_weak_slices: int = 2
    max_slices: int = MAX_TIME_SLICES

    def __post_init__(self) -> None:
        integer_values = (
            self.min_regime_count,
            self.min_time_slice_count,
            self.min_slices_per_regime,
            self.max_slices,
        )
        if any(value < 1 for value in integer_values):
            raise ValueError("count thresholds must be positive")
        if self.max_slices > 100_000:
            raise ValueError("max_slices must not exceed 100000")
        if self.max_consecutive_weak_slices < 0:
            raise ValueError("max_consecutive_weak_slices must be non-negative")

        decimal_values = (
            self.min_regime_relative_score_percent,
            self.max_regime_spread_percent,
            self.weak_slice_floor_percent,
            self.min_stable_time_fraction,
            self.max_time_degradation_percent,
        )
        if any(not value.is_finite() for value in decimal_values):
            raise ValueError("robustness thresholds must be finite")
        if self.min_regime_relative_score_percent < 0:
            raise ValueError("min_regime_relative_score_percent must be non-negative")
        if self.max_regime_spread_percent < 0:
            raise ValueError("max_regime_spread_percent must be non-negative")
        if self.weak_slice_floor_percent < 0:
            raise ValueError("weak_slice_floor_percent must be non-negative")
        if not Decimal("0") <= self.min_stable_time_fraction <= Decimal("1"):
            raise ValueError("min_stable_time_fraction must be in [0, 1]")
        if self.max_time_degradation_percent < 0:
            raise ValueError("max_time_degradation_percent must be non-negative")


@dataclass(frozen=True)
class RegimeRobustnessResult:
    regime: str
    slice_count: int
    sample_count: int
    weighted_score: Decimal
    relative_score_percent: Decimal
    degradation_percent: Decimal
    passed: bool


@dataclass(frozen=True)
class RegimeTimeRobustnessReport:
    overall_score: Decimal
    regime_results: tuple[RegimeRobustnessResult, ...]
    regime_spread_percent: Decimal
    stable_time_fraction: Decimal
    worst_time_degradation_percent: Decimal
    max_consecutive_weak_slices: int
    slice_count: int
    passed: bool
    evidence_fingerprint: str


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _weighted_score(slices: tuple[RegimeTimeSlice, ...]) -> Decimal:
    total_samples = sum(item.sample_count for item in slices)
    weighted_total = sum(
        (item.score * Decimal(item.sample_count) for item in slices),
        start=Decimal("0"),
    )
    return weighted_total / Decimal(total_samples)


def _longest_weak_run(
    slices: tuple[RegimeTimeSlice, ...],
    *,
    overall_score: Decimal,
    floor_percent: Decimal,
) -> int:
    hundred = Decimal("100")
    current = 0
    longest = 0
    for item in slices:
        relative = item.score / overall_score * hundred
        if relative < floor_percent:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _fingerprint(
    *,
    slices: tuple[RegimeTimeSlice, ...],
    thresholds: RegimeTimeThresholds,
    overall_score: Decimal,
    regime_results: tuple[RegimeRobustnessResult, ...],
    regime_spread_percent: Decimal,
    stable_time_fraction: Decimal,
    worst_time_degradation_percent: Decimal,
    max_consecutive_weak_slices: int,
    passed: bool,
) -> str:
    payload = {
        "overall_score": _decimal_text(overall_score),
        "passed": passed,
        "regime_spread_percent": _decimal_text(regime_spread_percent),
        "stable_time_fraction": _decimal_text(stable_time_fraction),
        "worst_time_degradation_percent": _decimal_text(
            worst_time_degradation_percent
        ),
        "max_consecutive_weak_slices": max_consecutive_weak_slices,
        "thresholds": {
            "min_regime_count": thresholds.min_regime_count,
            "min_time_slice_count": thresholds.min_time_slice_count,
            "min_slices_per_regime": thresholds.min_slices_per_regime,
            "min_regime_relative_score_percent": _decimal_text(
                thresholds.min_regime_relative_score_percent
            ),
            "max_regime_spread_percent": _decimal_text(
                thresholds.max_regime_spread_percent
            ),
            "weak_slice_floor_percent": _decimal_text(
                thresholds.weak_slice_floor_percent
            ),
            "min_stable_time_fraction": _decimal_text(
                thresholds.min_stable_time_fraction
            ),
            "max_time_degradation_percent": _decimal_text(
                thresholds.max_time_degradation_percent
            ),
            "max_consecutive_weak_slices": thresholds.max_consecutive_weak_slices,
            "max_slices": thresholds.max_slices,
        },
        "slices": [
            {
                "slice_id": item.slice_id,
                "regime": item.regime,
                "start_index": item.start_index,
                "end_index": item.end_index,
                "score": _decimal_text(item.score),
                "sample_count": item.sample_count,
            }
            for item in slices
        ],
        "regimes": [
            {
                "regime": item.regime,
                "slice_count": item.slice_count,
                "sample_count": item.sample_count,
                "weighted_score": _decimal_text(item.weighted_score),
                "relative_score_percent": _decimal_text(
                    item.relative_score_percent
                ),
                "degradation_percent": _decimal_text(item.degradation_percent),
                "passed": item.passed,
            }
            for item in regime_results
        ],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def qualify_regime_time_robustness(
    slices: tuple[RegimeTimeSlice, ...],
    *,
    thresholds: RegimeTimeThresholds = RegimeTimeThresholds(),
) -> RegimeTimeRobustnessReport:
    if len(slices) < thresholds.min_time_slice_count:
        raise ValueError("insufficient time slices for robustness qualification")
    if len(slices) > thresholds.max_slices:
        raise ValueError("time slice count exceeds max_slices")

    slice_ids = [item.slice_id for item in slices]
    if len(set(slice_ids)) != len(slice_ids):
        raise ValueError("slice_id values must be unique")

    ordered = tuple(
        sorted(slices, key=lambda item: (item.start_index, item.end_index, item.slice_id))
    )
    for previous, current in zip(ordered, ordered[1:]):
        if current.start_index < previous.end_index:
            raise ValueError("time slices must not overlap")

    regimes: dict[str, list[RegimeTimeSlice]] = defaultdict(list)
    for item in ordered:
        regimes[item.regime].append(item)
    if len(regimes) < thresholds.min_regime_count:
        raise ValueError("insufficient regime diversity for robustness qualification")

    overall_score = _weighted_score(ordered)
    if overall_score <= 0:
        raise ValueError("overall weighted score must be positive")

    hundred = Decimal("100")
    regime_results_list: list[RegimeRobustnessResult] = []
    for regime in sorted(regimes):
        regime_slices = tuple(regimes[regime])
        weighted_score = _weighted_score(regime_slices)
        relative_score = weighted_score / overall_score * hundred
        degradation = max(
            Decimal("0"),
            (overall_score - weighted_score) / overall_score * hundred,
        )
        regime_passed = (
            len(regime_slices) >= thresholds.min_slices_per_regime
            and relative_score >= thresholds.min_regime_relative_score_percent
        )
        regime_results_list.append(
            RegimeRobustnessResult(
                regime=regime,
                slice_count=len(regime_slices),
                sample_count=sum(item.sample_count for item in regime_slices),
                weighted_score=weighted_score,
                relative_score_percent=relative_score,
                degradation_percent=degradation,
                passed=regime_passed,
            )
        )

    regime_results = tuple(regime_results_list)
    regime_scores = tuple(item.weighted_score for item in regime_results)
    regime_spread = (max(regime_scores) - min(regime_scores)) / overall_score * hundred

    time_relative_scores = tuple(item.score / overall_score * hundred for item in ordered)
    stable_count = sum(
        value >= thresholds.weak_slice_floor_percent for value in time_relative_scores
    )
    stable_fraction = Decimal(stable_count) / Decimal(len(ordered))
    worst_time_degradation = max(
        (
            max(Decimal("0"), (overall_score - item.score) / overall_score * hundred)
            for item in ordered
        ),
        default=Decimal("0"),
    )
    longest_weak_run = _longest_weak_run(
        ordered,
        overall_score=overall_score,
        floor_percent=thresholds.weak_slice_floor_percent,
    )

    passed = (
        all(item.passed for item in regime_results)
        and regime_spread <= thresholds.max_regime_spread_percent
        and stable_fraction >= thresholds.min_stable_time_fraction
        and worst_time_degradation <= thresholds.max_time_degradation_percent
        and longest_weak_run <= thresholds.max_consecutive_weak_slices
    )
    evidence_fingerprint = _fingerprint(
        slices=ordered,
        thresholds=thresholds,
        overall_score=overall_score,
        regime_results=regime_results,
        regime_spread_percent=regime_spread,
        stable_time_fraction=stable_fraction,
        worst_time_degradation_percent=worst_time_degradation,
        max_consecutive_weak_slices=longest_weak_run,
        passed=passed,
    )
    return RegimeTimeRobustnessReport(
        overall_score=overall_score,
        regime_results=regime_results,
        regime_spread_percent=regime_spread,
        stable_time_fraction=stable_fraction,
        worst_time_degradation_percent=worst_time_degradation,
        max_consecutive_weak_slices=longest_weak_run,
        slice_count=len(ordered),
        passed=passed,
        evidence_fingerprint=evidence_fingerprint,
    )
