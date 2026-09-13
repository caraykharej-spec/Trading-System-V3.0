from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from statistics import median
from typing import Iterable


class BatchDecision(str, Enum):
    QUALIFIED = "QUALIFIED"
    QUALIFIED_WITH_LIMITS = "QUALIFIED_WITH_LIMITS"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    OVERFIT_SUSPECTED = "OVERFIT_SUSPECTED"
    FAILED_STATISTICAL_QUALIFICATION = "FAILED_STATISTICAL_QUALIFICATION"


@dataclass(frozen=True)
class QualificationRun:
    run_id: str
    dataset_version: str
    split: str
    seed: int
    strategy_fingerprint: str
    config_fingerprint: str
    cost_scenario: str
    trades: int
    wins: int
    gross_profit: Decimal
    gross_loss: Decimal
    net_pnl: Decimal
    max_drawdown_percent: Decimal

    def __post_init__(self) -> None:
        if not all(
            (
                self.run_id,
                self.dataset_version,
                self.strategy_fingerprint,
                self.config_fingerprint,
                self.cost_scenario,
            )
        ):
            raise ValueError("run identity and fingerprints are required")
        if self.split not in {"IS", "VALIDATION", "OOS", "WALK_FORWARD"}:
            raise ValueError("unsupported qualification split")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.trades < 0 or self.wins < 0 or self.wins > self.trades:
            raise ValueError("invalid trade counts")
        metrics = (
            self.gross_profit,
            self.gross_loss,
            self.net_pnl,
            self.max_drawdown_percent,
        )
        if any(not value.is_finite() for value in metrics):
            raise ValueError("qualification metrics must be finite")
        if (
            self.gross_profit < 0
            or self.gross_loss < 0
            or self.max_drawdown_percent < 0
        ):
            raise ValueError("profit, loss and drawdown magnitudes must be non-negative")

    @property
    def experiment_identity(self) -> tuple[str, str, str, str, str, int]:
        return (
            self.dataset_version,
            self.split,
            self.strategy_fingerprint,
            self.config_fingerprint,
            self.cost_scenario,
            self.seed,
        )

    @property
    def expectancy(self) -> Decimal | None:
        return self.net_pnl / Decimal(self.trades) if self.trades else None

    @property
    def profit_factor(self) -> Decimal | None:
        return self.gross_profit / self.gross_loss if self.gross_loss > 0 else None


@dataclass(frozen=True)
class BatchQualificationPolicy:
    minimum_runs: int = 1000
    minimum_is_runs: int = 200
    minimum_oos_runs: int = 200
    minimum_total_trades: int = 1000
    minimum_profit_factor: Decimal = Decimal("1.10")
    maximum_p95_drawdown_percent: Decimal = Decimal("25")
    maximum_is_oos_expectancy_degradation: Decimal = Decimal("0.35")

    def __post_init__(self) -> None:
        counts = (
            self.minimum_runs,
            self.minimum_is_runs,
            self.minimum_oos_runs,
            self.minimum_total_trades,
        )
        if any(value < 1 for value in counts):
            raise ValueError("qualification minimum counts must be positive")
        thresholds = (
            self.minimum_profit_factor,
            self.maximum_p95_drawdown_percent,
            self.maximum_is_oos_expectancy_degradation,
        )
        if any(not value.is_finite() for value in thresholds):
            raise ValueError("qualification policy thresholds must be finite")
        if self.minimum_profit_factor <= 0:
            raise ValueError("minimum profit factor must be positive")
        if self.maximum_p95_drawdown_percent < 0:
            raise ValueError("maximum drawdown must be non-negative")
        if not Decimal("0") <= self.maximum_is_oos_expectancy_degradation <= 1:
            raise ValueError("expectancy degradation must be in [0, 1]")


@dataclass(frozen=True)
class BatchQualificationReport:
    decision: BatchDecision
    run_count: int
    is_run_count: int
    oos_run_count: int
    total_trades: int
    win_rate_percent: Decimal
    profit_factor: Decimal | None
    mean_expectancy: Decimal | None
    aggregate_expectancy: Decimal | None
    expectancy_ci95_low: Decimal | None
    expectancy_ci95_high: Decimal | None
    p95_drawdown_percent: Decimal
    reasons: tuple[str, ...]


def _percentile(values: list[Decimal], percentile: Decimal) -> Decimal:
    ordered = sorted(values)
    index = math.ceil(float(percentile) * len(ordered)) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


def qualify_batch(
    runs: Iterable[QualificationRun],
    policy: BatchQualificationPolicy | None = None,
) -> BatchQualificationReport:
    applied = policy or BatchQualificationPolicy()
    items = tuple(runs)
    if len({item.run_id for item in items}) != len(items):
        raise ValueError("duplicate qualification run_id")
    if len({item.experiment_identity for item in items}) != len(items):
        raise ValueError("duplicate qualification experiment identity")

    in_sample = tuple(item for item in items if item.split == "IS")
    oos = tuple(item for item in items if item.split in {"OOS", "WALK_FORWARD"})
    total_trades = sum(item.trades for item in oos)
    wins = sum(item.wins for item in oos)
    gross_profit = sum((item.gross_profit for item in oos), Decimal("0"))
    gross_loss = sum((item.gross_loss for item in oos), Decimal("0"))
    net_pnl = sum((item.net_pnl for item in oos), Decimal("0"))
    win_rate = (
        Decimal(wins) / Decimal(total_trades) * Decimal("100")
        if total_trades
        else Decimal("0")
    )
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    aggregate_expectancy = (
        net_pnl / Decimal(total_trades) if total_trades else None
    )
    samples = [item.expectancy for item in oos if item.expectancy is not None]
    mean_expectancy: Decimal | None = None
    ci_low: Decimal | None = None
    ci_high: Decimal | None = None
    if samples:
        mean_expectancy = sum(samples, Decimal("0")) / Decimal(len(samples))
    if len(samples) >= 2 and mean_expectancy is not None:
        variance = sum(
            (value - mean_expectancy) ** 2 for value in samples
        ) / Decimal(len(samples) - 1)
        margin = Decimal("1.96") * (variance / Decimal(len(samples))).sqrt()
        ci_low, ci_high = mean_expectancy - margin, mean_expectancy + margin
    p95_drawdown = (
        _percentile([item.max_drawdown_percent for item in oos], Decimal("0.95"))
        if oos
        else Decimal("0")
    )

    reasons: list[str] = []
    if (
        len(items) < applied.minimum_runs
        or len(in_sample) < applied.minimum_is_runs
        or len(oos) < applied.minimum_oos_runs
    ):
        decision = BatchDecision.INSUFFICIENT_SAMPLE
        reasons.append("minimum independent IS/OOS run count not met")
    elif total_trades < applied.minimum_total_trades or ci_low is None:
        decision = BatchDecision.INSUFFICIENT_SAMPLE
        reasons.append("minimum OOS trade sample not met")
    else:
        is_expectancies = [
            item.expectancy
            for item in in_sample
            if item.expectancy is not None
        ]
        if not is_expectancies or not samples:
            decision = BatchDecision.INSUFFICIENT_SAMPLE
            reasons.append("usable IS/OOS expectancy evidence is missing")
        else:
            is_median = median(is_expectancies)
            oos_median = median(samples)
            degradation = Decimal("0")
            if is_median > 0:
                degradation = max(
                    Decimal("0"), (is_median - oos_median) / is_median
                )
            if degradation > applied.maximum_is_oos_expectancy_degradation:
                decision = BatchDecision.OVERFIT_SUSPECTED
                reasons.append("IS to OOS expectancy degradation exceeds policy")
            elif (
                profit_factor is None
                or profit_factor < applied.minimum_profit_factor
                or aggregate_expectancy is None
                or aggregate_expectancy <= 0
                or ci_low <= 0
                or p95_drawdown > applied.maximum_p95_drawdown_percent
            ):
                decision = BatchDecision.FAILED_STATISTICAL_QUALIFICATION
                reasons.append("OOS statistical or risk gate failed")
            else:
                decision = BatchDecision.QUALIFIED

    return BatchQualificationReport(
        decision,
        len(items),
        len(in_sample),
        len(oos),
        total_trades,
        win_rate,
        profit_factor,
        mean_expectancy,
        aggregate_expectancy,
        ci_low,
        ci_high,
        p95_drawdown,
        tuple(reasons),
    )
