from datetime import datetime, timezone

import pytest

from app.backtest.locked_oos import (
    seal_oos_plan,
    validate_walk_forward_boundaries,
)

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def test_oos_plan_is_chronological_sealed_and_reproducible():
    plan = seal_oos_plan(
        dataset_sha256="dataset-sha",
        strategy_fingerprint="strategy-sha",
        config_fingerprint="config-sha",
        total_observations=1000,
        sealed_at=NOW,
    )

    assert plan.train_range == range(0, 600)
    assert plan.validation_range == range(600, 800)
    assert plan.oos_range == range(800, 1000)
    assert len(plan.plan_sha256) == 64
    plan.verify(
        dataset_sha256="dataset-sha",
        strategy_fingerprint="strategy-sha",
        config_fingerprint="config-sha",
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("dataset_sha256", "changed", "dataset"),
        ("strategy_fingerprint", "changed", "strategy"),
        ("config_fingerprint", "changed", "configuration"),
    ),
)
def test_post_seal_changes_fail_closed(field, value, message):
    plan = seal_oos_plan(
        dataset_sha256="dataset-sha",
        strategy_fingerprint="strategy-sha",
        config_fingerprint="config-sha",
        total_observations=100,
        sealed_at=NOW,
    )
    inputs = {
        "dataset_sha256": "dataset-sha",
        "strategy_fingerprint": "strategy-sha",
        "config_fingerprint": "config-sha",
    }
    inputs[field] = value

    with pytest.raises(ValueError, match=message):
        plan.verify(**inputs)


def test_walk_forward_requires_strict_chronological_boundaries():
    validate_walk_forward_boundaries(
        ((0, 60, 60, 80), (20, 80, 80, 100)),
        total_observations=100,
    )

    with pytest.raises(ValueError, match="boundary"):
        validate_walk_forward_boundaries(
            ((0, 60, 59, 80),),
            total_observations=100,
        )


def test_walk_forward_rejects_overlapping_oos_windows():
    with pytest.raises(ValueError, match="must not overlap"):
        validate_walk_forward_boundaries(
            ((0, 60, 60, 90), (10, 70, 70, 100)),
            total_observations=100,
        )
