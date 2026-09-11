from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.backtest.models import BacktestResult
from app.backtest.walk_forward import WalkForwardResult, WalkForwardWindow
from app.strategy_validation import (
    CalibrationObservation,
    CalibrationStatus,
    StrategyValidationEvidence,
    StrategyValidationPolicy,
    ThresholdCalibrationConfig,
    ThresholdCalibrator,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _observation(
    index: int,
    *,
    oos_return: str,
    profit_factor: str,
    drawdown: str,
    walk_forward_ratio: str,
    monte_carlo_return: str,
    monte_carlo_drawdown: str,
    cost_degradation: str,
    parameter_spread: str,
    feasible_ratio: str,
    forward_hit_rate: str,
    forward_mean_return: str,
    as_of: datetime | None = None,
) -> CalibrationObservation:
    return CalibrationObservation(
        sample_id=f"sample-{index}",
        as_of=as_of or NOW + timedelta(days=index),
        oos_return_percent=Decimal(oos_return),
        oos_profit_factor=Decimal(profit_factor),
        oos_drawdown_percent=Decimal(drawdown),
        profitable_walk_forward_ratio=Decimal(walk_forward_ratio),
        monte_carlo_median_return_percent=Decimal(monte_carlo_return),
        monte_carlo_worst_drawdown_percent=Decimal(monte_carlo_drawdown),
        cost_stress_degradation_percent=Decimal(cost_degradation),
        parameter_normalized_spread=Decimal(parameter_spread),
        feasible_trial_ratio=Decimal(feasible_ratio),
        forward_hit_rate_percent=Decimal(forward_hit_rate),
        forward_mean_return_percent=Decimal(forward_mean_return),
    )


def _strong_cohort() -> tuple[CalibrationObservation, ...]:
    rows = (
        ("2", "1.2", "5", "0.60", "1", "20", "10", "0.10", "0.60", "55", "0.2"),
        ("4", "1.4", "10", "0.70", "2", "25", "15", "0.15", "0.70", "60", "0.4"),
        ("6", "1.6", "15", "0.80", "3", "30", "20", "0.20", "0.80", "65", "0.6"),
        ("8", "1.8", "20", "0.90", "4", "35", "25", "0.25", "0.90", "70", "0.8"),
    )
    return tuple(
        _observation(
            index,
            oos_return=row[0],
            profit_factor=row[1],
            drawdown=row[2],
            walk_forward_ratio=row[3],
            monte_carlo_return=row[4],
            monte_carlo_drawdown=row[5],
            cost_degradation=row[6],
            parameter_spread=row[7],
            feasible_ratio=row[8],
            forward_hit_rate=row[9],
            forward_mean_return=row[10],
        )
        for index, row in enumerate(rows)
    )


def _config(minimum_samples: int = 4) -> ThresholdCalibrationConfig:
    return ThresholdCalibrationConfig(
        minimum_samples=minimum_samples,
        minimum_metric_samples=minimum_samples,
        lower_quantile=Decimal("0.25"),
        upper_quantile=Decimal("0.75"),
    )


def test_calibration_tightens_thresholds_from_empirical_quantiles() -> None:
    report = ThresholdCalibrator(config=_config()).calibrate(_strong_cohort())

    assert report.status is CalibrationStatus.CALIBRATED
    assert report.calibrated
    policy = report.require_policy()
    assert policy.min_oos_return_percent == Decimal("3.50")
    assert policy.min_oos_profit_factor == Decimal("1.350")
    assert policy.max_oos_drawdown_percent == Decimal("16.25")
    assert policy.min_profitable_walk_forward_ratio == Decimal("0.6750")
    assert policy.min_monte_carlo_median_return_percent == Decimal("1.75")
    assert policy.max_monte_carlo_worst_drawdown_percent == Decimal("31.25")
    assert policy.max_cost_stress_degradation_percent == Decimal("21.25")
    assert policy.max_parameter_normalized_spread == Decimal("0.2125")
    assert policy.min_feasible_trial_ratio == Decimal("0.6750")
    assert policy.min_forward_hit_rate_percent == Decimal("58.75")
    assert policy.min_forward_mean_return_percent == Decimal("0.350")
    assert all(item.sample_count == 4 for item in report.thresholds)
    assert all(item.tightened for item in report.thresholds)


def test_weak_cohort_cannot_loosen_phase_38_guardrails() -> None:
    rows = tuple(
        _observation(
            index,
            oos_return=value,
            profit_factor="0.7",
            drawdown="40",
            walk_forward_ratio="0.20",
            monte_carlo_return="-5",
            monte_carlo_drawdown="60",
            cost_degradation="70",
            parameter_spread="0.60",
            feasible_ratio="0.20",
            forward_hit_rate="30",
            forward_mean_return="-1",
        )
        for index, value in enumerate(("-5", "-4", "-3", "-2"))
    )
    baseline = StrategyValidationPolicy()
    policy = ThresholdCalibrator(baseline=baseline, config=_config()).calibrate(rows).require_policy()

    assert policy.min_oos_return_percent == baseline.min_oos_return_percent
    assert policy.min_oos_profit_factor == baseline.min_oos_profit_factor
    assert policy.max_oos_drawdown_percent == baseline.max_oos_drawdown_percent
    assert policy.min_profitable_walk_forward_ratio == baseline.min_profitable_walk_forward_ratio
    assert (
        policy.min_monte_carlo_median_return_percent
        == baseline.min_monte_carlo_median_return_percent
    )
    assert (
        policy.max_monte_carlo_worst_drawdown_percent
        == baseline.max_monte_carlo_worst_drawdown_percent
    )
    assert (
        policy.max_cost_stress_degradation_percent
        == baseline.max_cost_stress_degradation_percent
    )
    assert policy.max_parameter_normalized_spread == baseline.max_parameter_normalized_spread
    assert policy.min_feasible_trial_ratio == baseline.min_feasible_trial_ratio
    assert policy.min_forward_hit_rate_percent == baseline.min_forward_hit_rate_percent
    assert policy.min_forward_mean_return_percent == baseline.min_forward_mean_return_percent


def test_insufficient_calibration_cohort_holds_without_policy() -> None:
    report = ThresholdCalibrator(config=_config()).calibrate(_strong_cohort()[:3])

    assert report.status is CalibrationStatus.HOLD
    assert not report.calibrated
    assert report.policy is None
    assert any(reason.startswith("insufficient_calibration_cohort") for reason in report.reasons)
    with pytest.raises(ValueError):
        report.require_policy()


def test_missing_metric_samples_fail_closed() -> None:
    rows = list(_strong_cohort())
    first = rows[0]
    rows[0] = CalibrationObservation(
        sample_id=first.sample_id,
        as_of=first.as_of,
        oos_return_percent=first.oos_return_percent,
        oos_profit_factor=first.oos_profit_factor,
        oos_drawdown_percent=first.oos_drawdown_percent,
        profitable_walk_forward_ratio=first.profitable_walk_forward_ratio,
        monte_carlo_median_return_percent=first.monte_carlo_median_return_percent,
        monte_carlo_worst_drawdown_percent=first.monte_carlo_worst_drawdown_percent,
        cost_stress_degradation_percent=first.cost_stress_degradation_percent,
        parameter_normalized_spread=None,
        feasible_trial_ratio=first.feasible_trial_ratio,
        forward_hit_rate_percent=first.forward_hit_rate_percent,
        forward_mean_return_percent=first.forward_mean_return_percent,
    )

    report = ThresholdCalibrator(config=_config()).calibrate(rows)

    assert report.status is CalibrationStatus.HOLD
    assert report.policy is None
    assert "insufficient_metric_samples:max_parameter_normalized_spread:3<4" in report.reasons


def test_duplicate_sample_ids_are_rejected_to_prevent_overweighting() -> None:
    rows = _strong_cohort()
    duplicate = CalibrationObservation(
        sample_id=rows[0].sample_id,
        as_of=NOW + timedelta(days=10),
        oos_return_percent=Decimal("20"),
    )

    with pytest.raises(ValueError, match="duplicate calibration sample_id"):
        ThresholdCalibrator(config=_config()).calibrate(rows + (duplicate,))


def test_cutoff_excludes_future_evidence_and_prevents_temporal_leakage() -> None:
    rows = _strong_cohort()
    cutoff = NOW + timedelta(days=3)
    report = ThresholdCalibrator(config=_config(minimum_samples=3)).calibrate(
        rows,
        cutoff=cutoff,
    )

    assert report.status is CalibrationStatus.CALIBRATED
    assert report.source_sample_count == 4
    assert report.eligible_sample_count == 3
    assert report.require_policy().min_oos_return_percent == Decimal("3.0")


def test_dataset_fingerprint_is_stable_across_input_order() -> None:
    rows = _strong_cohort()
    first = ThresholdCalibrator(config=_config()).calibrate(rows)
    second = ThresholdCalibrator(config=_config()).calibrate(tuple(reversed(rows)))

    assert first.dataset_fingerprint == second.dataset_fingerprint
    assert len(first.dataset_fingerprint) == 64


def test_observation_can_be_built_from_phase_38_evidence() -> None:
    holdout = BacktestResult(
        initial_equity=Decimal("10000"),
        final_equity=Decimal("10500"),
        trades=(),
        rejected_signals=0,
        open_positions_at_end=0,
        max_drawdown_percent=Decimal("7"),
        win_rate_percent=Decimal("60"),
        profit_factor=Decimal("1.8"),
        total_return_percent=Decimal("5"),
        max_concurrent_positions=1,
    )
    walk_forward = WalkForwardResult(
        windows=(
            WalkForwardWindow(0, 10, 10, 20),
            WalkForwardWindow(10, 20, 20, 30),
        ),
        results=(holdout, BacktestResult(
            initial_equity=Decimal("10000"),
            final_equity=Decimal("9900"),
            trades=(),
            rejected_signals=0,
            open_positions_at_end=0,
            max_drawdown_percent=Decimal("9"),
            win_rate_percent=Decimal("40"),
            profit_factor=Decimal("0.9"),
            total_return_percent=Decimal("-1"),
            max_concurrent_positions=1,
        )),
    )
    observation = CalibrationObservation.from_evidence(
        "historical-1",
        NOW,
        StrategyValidationEvidence(holdout=holdout, walk_forward=walk_forward),
    )

    assert observation.oos_return_percent == Decimal("5")
    assert observation.oos_profit_factor == Decimal("1.8")
    assert observation.oos_drawdown_percent == Decimal("7")
    assert observation.profitable_walk_forward_ratio == Decimal("0.5")
    assert observation.monte_carlo_median_return_percent is None


def test_calibration_config_rejects_invalid_quantile_geometry() -> None:
    with pytest.raises(ValueError):
        ThresholdCalibrationConfig(lower_quantile=Decimal("0.80"))
    with pytest.raises(ValueError):
        ThresholdCalibrationConfig(upper_quantile=Decimal("0.20"))
