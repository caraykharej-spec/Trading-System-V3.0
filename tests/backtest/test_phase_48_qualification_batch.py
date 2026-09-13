from decimal import Decimal

import pytest

from app.backtest.qualification_batch import (
    BatchDecision,
    QualificationRun,
    qualify_batch,
)


def run(index: int, split: str, pnl: str = "20") -> QualificationRun:
    return QualificationRun(
        run_id=f"run-{index}",
        dataset_version="1.0.0",
        split=split,
        trades=10,
        wins=6,
        gross_profit=Decimal("80"),
        gross_loss=Decimal("50"),
        net_pnl=Decimal(pnl),
        max_drawdown_percent=Decimal("10"),
    )


def test_one_thousand_run_batch_requires_positive_oos_confidence_bound():
    runs = tuple(
        run(index, "IS" if index < 500 else "OOS")
        for index in range(1000)
    )

    report = qualify_batch(runs)

    assert report.decision is BatchDecision.QUALIFIED
    assert report.run_count == 1000
    assert report.oos_run_count == 500
    assert report.total_trades == 5000
    assert report.profit_factor == Decimal("1.6")
    assert report.expectancy_ci95_low is not None
    assert report.expectancy_ci95_low > 0


def test_successful_execution_count_cannot_replace_statistical_quality():
    runs = tuple(
        run(index, "IS" if index < 500 else "OOS", "-10")
        for index in range(1000)
    )

    report = qualify_batch(runs)

    assert report.decision is BatchDecision.FAILED_STATISTICAL_QUALIFICATION
    assert report.mean_expectancy is not None
    assert report.mean_expectancy < 0


def test_less_than_one_thousand_runs_is_insufficient_sample():
    report = qualify_batch(tuple(run(index, "OOS") for index in range(999)))

    assert report.decision is BatchDecision.INSUFFICIENT_SAMPLE


def test_duplicate_run_identity_fails_closed():
    with pytest.raises(ValueError, match="duplicate"):
        qualify_batch((run(1, "OOS"), run(1, "OOS")))
