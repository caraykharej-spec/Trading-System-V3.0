from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from app.backtest.models import BacktestResult, TradeRecord
from app.backtest.portfolio import PortfolioBacktestResult

from .models import EvaluationSummary, ObjectiveMetric, ResearchConstraints


def _profit_factor(trades: Iterable[TradeRecord]) -> Decimal | None:
    rows = tuple(trades)
    gross_profit = sum(
        (trade.realized_pnl for trade in rows if trade.realized_pnl > 0), Decimal("0")
    )
    gross_loss = sum(
        (-trade.realized_pnl for trade in rows if trade.realized_pnl < 0), Decimal("0")
    )
    if gross_loss > 0:
        return gross_profit / gross_loss
    return None if gross_profit == 0 else Decimal("Infinity")


def _win_rate(trades: Iterable[TradeRecord]) -> Decimal:
    rows = tuple(trades)
    if not rows:
        return Decimal("0")
    wins = sum(1 for trade in rows if trade.realized_pnl > 0)
    return Decimal(wins) / Decimal(len(rows)) * Decimal("100")


def summarize_backtest(result: BacktestResult) -> EvaluationSummary:
    return EvaluationSummary(
        total_return_percent=result.total_return_percent,
        max_drawdown_percent=result.max_drawdown_percent,
        win_rate_percent=result.win_rate_percent,
        profit_factor=result.profit_factor,
        trade_count=len(result.trades),
        rejected_signals=result.rejected_signals,
        window_count=0,
    )


def summarize_portfolio_backtest(result: PortfolioBacktestResult) -> EvaluationSummary:
    trades = tuple(
        trade
        for symbol_result in result.results.values()
        for trade in symbol_result.trades
    )
    return EvaluationSummary(
        total_return_percent=result.total_return_percent,
        max_drawdown_percent=result.max_drawdown_percent,
        win_rate_percent=_win_rate(trades),
        profit_factor=_profit_factor(trades),
        trade_count=result.total_trades,
        rejected_signals=sum(item.rejected_signals for item in result.results.values()),
        window_count=0,
    )


def summarize_backtests(results: Iterable[BacktestResult]) -> EvaluationSummary:
    rows = tuple(results)
    if not rows:
        return EvaluationSummary(
            total_return_percent=Decimal("0"),
            max_drawdown_percent=Decimal("0"),
            win_rate_percent=Decimal("0"),
            profit_factor=None,
            trade_count=0,
            rejected_signals=0,
            window_count=0,
        )

    trades = tuple(trade for result in rows for trade in result.trades)
    mean_return = sum(
        (result.total_return_percent for result in rows), Decimal("0")
    ) / Decimal(len(rows))
    return EvaluationSummary(
        total_return_percent=mean_return,
        max_drawdown_percent=max(result.max_drawdown_percent for result in rows),
        win_rate_percent=_win_rate(trades),
        profit_factor=_profit_factor(trades),
        trade_count=len(trades),
        rejected_signals=sum(result.rejected_signals for result in rows),
        window_count=len(rows),
    )


def objective_value(summary: EvaluationSummary, metric: ObjectiveMetric) -> Decimal:
    if metric is ObjectiveMetric.TOTAL_RETURN_PERCENT:
        return summary.total_return_percent
    if metric is ObjectiveMetric.WIN_RATE_PERCENT:
        return summary.win_rate_percent
    if metric is ObjectiveMetric.RETURN_DRAWDOWN_RATIO:
        denominator = max(summary.max_drawdown_percent, Decimal("1"))
        return summary.total_return_percent / denominator
    raise ValueError(f"unsupported objective metric: {metric}")


def constraint_violations(
    summary: EvaluationSummary,
    constraints: ResearchConstraints,
    *,
    prefix: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if summary.trade_count < constraints.min_trades:
        reasons.append(f"{prefix}: trade count below minimum")
    if (
        constraints.max_drawdown_percent is not None
        and summary.max_drawdown_percent > constraints.max_drawdown_percent
    ):
        reasons.append(f"{prefix}: max drawdown above limit")
    if constraints.min_profit_factor is not None:
        profit_factor = summary.profit_factor
        if profit_factor is None or profit_factor < constraints.min_profit_factor:
            reasons.append(f"{prefix}: profit factor below minimum")
    if summary.window_count < constraints.min_oos_windows:
        reasons.append(f"{prefix}: OOS window count below minimum")
    return tuple(reasons)


def validation_degradation_percent(
    training_objective: Decimal, validation_objective: Decimal
) -> Decimal:
    if validation_objective >= training_objective:
        return Decimal("0")
    if training_objective > 0:
        return (training_objective - validation_objective) / training_objective * Decimal("100")
    if training_objective == 0:
        return Decimal("100") if validation_objective < 0 else Decimal("0")
    return Decimal("100") if validation_objective < training_objective else Decimal("0")
