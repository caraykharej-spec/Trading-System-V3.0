from datetime import datetime, timezone

import pytest

from app.backtest.locked_oos import seal_oos_plan
from scripts.backtest.hf_qualified_data import asset_execution_status
from scripts.backtest.run_phase_48_2_locked_oos import (
    build_pre_oos_walk_forward_windows,
)

NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def test_60_20_20_plan_and_walk_forward_never_touch_locked_oos() -> None:
    plan = seal_oos_plan(
        dataset_sha256="d" * 64,
        strategy_fingerprint="s" * 64,
        config_fingerprint="c" * 64,
        total_observations=1000,
        sealed_at=NOW,
    )
    assert (plan.train_end, plan.validation_end, plan.oos_end) == (600, 800, 1000)
    windows = build_pre_oos_walk_forward_windows(
        validation_end=plan.validation_end,
        window_count=3,
    )
    assert len(windows) == 3
    assert windows[-1][3] == 800
    assert all(
        test_end <= plan.validation_end
        for _, _, _, test_end in windows
    )
    assert all(
        train_end == test_start
        for _, train_end, test_start, _ in windows
    )


def test_walk_forward_window_count_must_be_positive() -> None:
    with pytest.raises(ValueError, match="window_count"):
        build_pre_oos_walk_forward_windows(
            validation_end=800,
            window_count=0,
        )


def test_listing_limited_pending_remains_non_performance_evidence() -> None:
    assert asset_execution_status(
        {
            "base_asset": "SKY",
            "qualification_status": "QUALIFIED_LISTING_LIMITED_HISTORY",
            "strategy_warmup_status": "PENDING_MINIMUM_CANDLES",
        }
    ) == "WARMUP_PENDING"


def test_normal_qualified_asset_executes() -> None:
    assert asset_execution_status(
        {
            "base_asset": "TON",
            "qualification_status": "QUALIFIED",
            "strategy_warmup_status": "READY",
        }
    ) == "COMPLETE"
