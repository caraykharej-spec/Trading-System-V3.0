from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from app.backtest.engine import BacktestEngine
from app.backtest.models import BacktestConfig, BacktestResult
from app.data.market_data import Candle
from app.strategy.rules import DEFAULT_RULES, StrategyRules


@dataclass(frozen=True)
class CostStressScenario:
    name: str
    commission_percent: Decimal
    spread_percent: Decimal
    slippage_percent: Decimal
    funding_rate_percent_per_day: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("stress scenario name cannot be blank")
        for value in (
            self.commission_percent,
            self.spread_percent,
            self.slippage_percent,
        ):
            if value < 0:
                raise ValueError("stress costs must be non-negative")


@dataclass(frozen=True)
class CostStressOutcome:
    scenario: CostStressScenario
    result: BacktestResult
    return_degradation_percent: Decimal
    drawdown_increase_points: Decimal


@dataclass(frozen=True)
class CostStressReport:
    baseline: BacktestResult
    outcomes: tuple[CostStressOutcome, ...]

    @property
    def worst_return_degradation_percent(self) -> Decimal:
        return max(
            (item.return_degradation_percent for item in self.outcomes),
            default=Decimal("0"),
        )


def _degradation_percent(baseline: Decimal, stressed: Decimal) -> Decimal:
    denominator = max(abs(baseline), Decimal("1"))
    return max(Decimal("0"), (baseline - stressed) / denominator * Decimal("100"))


def run_cost_stress_validation(
    symbol: str,
    candles_by_timeframe: dict[str, list[Candle]],
    *,
    base_config: BacktestConfig,
    scenarios: tuple[CostStressScenario, ...],
    rules: StrategyRules = DEFAULT_RULES,
    evaluation_start: datetime | None = None,
) -> CostStressReport:
    baseline = BacktestEngine(base_config, rules=rules).run(
        symbol,
        candles_by_timeframe,
        evaluation_start=evaluation_start,
    )
    outcomes: list[CostStressOutcome] = []

    for scenario in scenarios:
        stressed_config = replace(
            base_config,
            commission_percent=scenario.commission_percent,
            spread_percent=scenario.spread_percent,
            slippage_percent=scenario.slippage_percent,
            funding_rate_percent_per_day=scenario.funding_rate_percent_per_day,
        )
        result = BacktestEngine(stressed_config, rules=rules).run(
            symbol,
            candles_by_timeframe,
            evaluation_start=evaluation_start,
        )
        outcomes.append(
            CostStressOutcome(
                scenario=scenario,
                result=result,
                return_degradation_percent=_degradation_percent(
                    baseline.total_return_percent,
                    result.total_return_percent,
                ),
                drawdown_increase_points=max(
                    Decimal("0"),
                    result.max_drawdown_percent - baseline.max_drawdown_percent,
                ),
            )
        )
    return CostStressReport(baseline=baseline, outcomes=tuple(outcomes))
