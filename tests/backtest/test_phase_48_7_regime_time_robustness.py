from decimal import Decimal

import pytest

from app.backtest.regime_time_robustness import (
    RegimeTimeSlice,
    RegimeTimeThresholds,
    qualify_regime_time_robustness,
)


def _slice(
    index: int,
    regime: str,
    score: str,
    *,
    sample_count: int = 10,
) -> RegimeTimeSlice:
    return RegimeTimeSlice(
        slice_id=f"slice-{index}",
        regime=regime,
        start_index=index * 10,
        end_index=(index + 1) * 10,
        score=Decimal(score),
        sample_count=sample_count,
    )


def _balanced_slices() -> tuple[RegimeTimeSlice, ...]:
    return (
        _slice(0, "TREND", "100"),
        _slice(1, "RANGE", "90"),
        _slice(2, "TREND", "95"),
        _slice(3, "RANGE", "92"),
    )


def test_balanced_regimes_and_time_windows_pass_reproducibly():
    first = qualify_regime_time_robustness(_balanced_slices())
    second = qualify_regime_time_robustness(tuple(reversed(_balanced_slices())))

    assert first.passed is True
    assert first == second
    assert first.slice_count == 4
    assert len(first.regime_results) == 2
    assert len(first.evidence_fingerprint) == 64


def test_bad_regime_fails_relative_score_gate():
    slices = (
        _slice(0, "TREND", "120"),
        _slice(1, "RANGE", "20"),
        _slice(2, "TREND", "120"),
        _slice(3, "RANGE", "20"),
    )
    report = qualify_regime_time_robustness(slices)

    range_result = next(item for item in report.regime_results if item.regime == "RANGE")
    assert report.passed is False
    assert range_result.passed is False


def test_regime_spread_gate_detects_concentration():
    thresholds = RegimeTimeThresholds(
        min_regime_relative_score_percent=Decimal("0"),
        max_regime_spread_percent=Decimal("20"),
        weak_slice_floor_percent=Decimal("0"),
        min_stable_time_fraction=Decimal("0"),
        max_time_degradation_percent=Decimal("100"),
    )
    slices = (
        _slice(0, "TREND", "120"),
        _slice(1, "RANGE", "70"),
        _slice(2, "TREND", "120"),
        _slice(3, "RANGE", "70"),
    )

    report = qualify_regime_time_robustness(slices, thresholds=thresholds)

    assert report.passed is False
    assert report.regime_spread_percent > Decimal("20")


def test_worst_time_degradation_gate_rejects_single_era_failure():
    thresholds = RegimeTimeThresholds(
        min_regime_relative_score_percent=Decimal("0"),
        max_regime_spread_percent=Decimal("100"),
        weak_slice_floor_percent=Decimal("0"),
        min_stable_time_fraction=Decimal("0"),
        max_time_degradation_percent=Decimal("30"),
    )
    slices = (
        _slice(0, "TREND", "100"),
        _slice(1, "RANGE", "100"),
        _slice(2, "TREND", "100"),
        _slice(3, "RANGE", "20"),
    )

    report = qualify_regime_time_robustness(slices, thresholds=thresholds)

    assert report.passed is False
    assert report.worst_time_degradation_percent > Decimal("30")


def test_consecutive_weak_windows_fail_closed():
    thresholds = RegimeTimeThresholds(
        min_regime_relative_score_percent=Decimal("0"),
        max_regime_spread_percent=Decimal("100"),
        weak_slice_floor_percent=Decimal("80"),
        min_stable_time_fraction=Decimal("0"),
        max_time_degradation_percent=Decimal("100"),
        max_consecutive_weak_slices=1,
    )
    slices = (
        _slice(0, "TREND", "100"),
        _slice(1, "RANGE", "40"),
        _slice(2, "TREND", "40"),
        _slice(3, "RANGE", "100"),
    )

    report = qualify_regime_time_robustness(slices, thresholds=thresholds)

    assert report.passed is False
    assert report.max_consecutive_weak_slices == 2


def test_regime_requires_minimum_slice_replication():
    thresholds = RegimeTimeThresholds(min_slices_per_regime=2)
    slices = (
        _slice(0, "TREND", "100"),
        _slice(1, "TREND", "100"),
        _slice(2, "TREND", "100"),
        _slice(3, "RANGE", "100"),
    )

    report = qualify_regime_time_robustness(slices, thresholds=thresholds)

    range_result = next(item for item in report.regime_results if item.regime == "RANGE")
    assert range_result.passed is False
    assert report.passed is False


def test_insufficient_regime_diversity_is_rejected():
    slices = tuple(_slice(index, "TREND", "100") for index in range(4))

    with pytest.raises(ValueError, match="regime diversity"):
        qualify_regime_time_robustness(slices)


def test_insufficient_time_slices_are_rejected():
    slices = (
        _slice(0, "TREND", "100"),
        _slice(1, "RANGE", "100"),
        _slice(2, "TREND", "100"),
    )

    with pytest.raises(ValueError, match="insufficient time slices"):
        qualify_regime_time_robustness(slices)


def test_overlapping_time_slices_are_rejected():
    slices = list(_balanced_slices())
    slices[1] = RegimeTimeSlice(
        slice_id="overlap",
        regime="RANGE",
        start_index=5,
        end_index=15,
        score=Decimal("90"),
    )

    with pytest.raises(ValueError, match="must not overlap"):
        qualify_regime_time_robustness(tuple(slices))


def test_duplicate_slice_ids_are_rejected():
    slices = list(_balanced_slices())
    slices[1] = RegimeTimeSlice(
        slice_id=slices[0].slice_id,
        regime=slices[1].regime,
        start_index=slices[1].start_index,
        end_index=slices[1].end_index,
        score=slices[1].score,
    )

    with pytest.raises(ValueError, match="must be unique"):
        qualify_regime_time_robustness(tuple(slices))


@pytest.mark.parametrize("score", ("NaN", "Infinity", "-Infinity"))
def test_non_finite_slice_scores_are_rejected(score):
    with pytest.raises(ValueError, match="finite"):
        _slice(0, "TREND", score)


def test_non_positive_overall_score_is_rejected():
    slices = (
        _slice(0, "TREND", "1"),
        _slice(1, "RANGE", "-1"),
        _slice(2, "TREND", "1"),
        _slice(3, "RANGE", "-1"),
    )

    with pytest.raises(ValueError, match="overall weighted score must be positive"):
        qualify_regime_time_robustness(slices)


def test_slice_cardinality_is_bounded():
    thresholds = RegimeTimeThresholds(max_slices=4)
    slices = tuple(
        _slice(index, "TREND" if index % 2 == 0 else "RANGE", "100")
        for index in range(5)
    )

    with pytest.raises(ValueError, match="max_slices"):
        qualify_regime_time_robustness(slices, thresholds=thresholds)
