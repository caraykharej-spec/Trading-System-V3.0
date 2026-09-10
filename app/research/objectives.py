from __future__ import annotations

from decimal import Decimal

from app.backtest.models import BacktestResult

from .models import ObjectiveDirection, ObjectiveMetric, ResearchConstraints


def objective_value(result: BacktestResult, metric: ObjectiveMetric) -> Decimal | None:
    if metric is ObjectiveMetric.TOTAL_RETURN_PERCENT:
        return result.total_return_percent
    if metric is ObjectiveMetric.FINAL_EQUITY:
        return result.final_equity
    if metric is ObjectiveMetric.PROFIT_FACTOR:
        return result.profit_factor
    if metric is ObjectiveMetric.MAX_DRAWDOWN_PERCENT:
        return result.max_drawdown_percent
    if metric is ObjectiveMetric.WIN_RATE_PERCENT:
        return result.win_rate_percent
    raise ValueError(f"unsupported objective metric: {metric}")


def constraint_failure(result: BacktestResult, constraints: ResearchConstraints) -> str | None:
    if len(result.trades) < constraints.min_trades:
        return "MIN_TRADES"
    if (
        constraints.max_drawdown_percent is not None
        and result.max_drawdown_percent > constraints.max_drawdown_percent
    ):
        return "MAX_DRAWDOWN"
    if constraints.min_profit_factor is not None:
        if result.profit_factor is None or result.profit_factor < constraints.min_profit_factor:
            return "MIN_PROFIT_FACTOR"
    if (
        constraints.min_total_return_percent is not None
        and result.total_return_percent < constraints.min_total_return_percent
    ):
        return "MIN_TOTAL_RETURN"
    return None


def better(
    candidate: Decimal,
    incumbent: Decimal,
    direction: ObjectiveDirection,
) -> bool:
    if direction is ObjectiveDirection.MAXIMIZE:
        return candidate > incumbent
    return candidate < incumbent
