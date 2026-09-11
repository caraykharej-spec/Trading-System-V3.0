import pytest

from app.strategy_validation import (
    CalibrationStatus,
    StrategyQualificationEngine,
    StrategyValidationPolicy,
    ThresholdCalibrationReport,
)


def test_qualification_engine_accepts_only_calibrated_policy() -> None:
    policy = StrategyValidationPolicy()
    calibrated = ThresholdCalibrationReport(
        status=CalibrationStatus.CALIBRATED,
        source_sample_count=20,
        eligible_sample_count=20,
        dataset_fingerprint="a" * 64,
        thresholds=(),
        reasons=(),
        policy=policy,
    )
    engine = StrategyQualificationEngine.from_calibration(calibrated)
    assert engine.policy == policy

    hold = ThresholdCalibrationReport(
        status=CalibrationStatus.HOLD,
        source_sample_count=3,
        eligible_sample_count=3,
        dataset_fingerprint="b" * 64,
        thresholds=(),
        reasons=("insufficient_calibration_cohort:3<20",),
        policy=None,
    )
    with pytest.raises(ValueError, match="does not contain an approved policy"):
        StrategyQualificationEngine.from_calibration(hold)
