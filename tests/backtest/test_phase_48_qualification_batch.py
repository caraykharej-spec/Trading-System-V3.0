from decimal import Decimal

import pytest

from app.backtest.qualification_batch import (
    BatchDecision,
    QualificationRun,
    qualify_batch,
)


def run(
    index: int,
    split: str,
    pnl: str = "20",
    *,
    trades: int = 10,
    run_id: str | None = None,
) -> QualificationRun:
    return QualificationRun(
        run_id=run_id or f"run-{index}",
        dataset_version="1.0.0",
        split=split,
        seed=index,
        strategy_fingerprint="strategy-sha",
        config_fingerprint="config-sha",
        cost_scenario="baseline",
        trades=trades,
        wins=min(6, trades),
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
    assert report.is_run_count == 500
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
    assert report.aggregate_expectancy is not None
    assert report.aggregate_expectancy < 0


def test_trade_weighted_negative_expectancy_cannot_qualify():
    runs = [run(index, "IS") for index in range(500)]
    runs.extend(run(index, "OOS", "10", trades=1) for index in range(500, 999))
    runs.append(run(999, "OOS", "-10000", trades=10000))

    report = qualify_batch(runs)

    assert report.aggregate_expectancy is not None
    assert report.aggregate_expectancy < 0
    assert report.decision is BatchDecision.FAILED_STATISTICAL_QUALIFICATION


def test_less_than_one_thousand_runs_is_insufficient_sample():
    report = qualify_batch(
        tuple(
            run(index, "IS" if index < 500 else "OOS")
            for index in range(999)
        )
    )

    assert report.decision is BatchDecision.INSUFFICIENT_SAMPLE


def test_missing_is_baseline_is_insufficient_sample():
    report = qualify_batch(tuple(run(index, "OOS") for index in range(1000)))

    assert report.decision is BatchDecision.INSUFFICIENT_SAMPLE


def test_duplicate_experiment_identity_fails_closed():
    first = run(1, "OOS")
    replay = QualificationRun(
        **{**first.__dict__, "run_id": "renamed-replay"}
    )
    with pytest.raises(ValueError, match="experiment identity"):
        qualify_batch((first, replay))


def test_non_finite_metrics_fail_closed():
    invalid = run(1, "OOS")
    with pytest.raises(ValueError, match="finite"):
        QualificationRun(
            **{**invalid.__dict__, "net_pnl": Decimal("Infinity")}
        )
