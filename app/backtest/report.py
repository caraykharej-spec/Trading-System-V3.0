from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from .models import BacktestResult


@dataclass(frozen=True)
class BacktestReport:
    symbol: str
    initial_equity: Decimal
    final_equity: Decimal
    return_percent: Decimal
    max_drawdown_percent: Decimal
    win_rate_percent: Decimal
    profit_factor: Decimal | None
    trades: int
    rejected_signals: int
    max_concurrent_positions: int

    @property
    def net_pnl(self) -> Decimal:
        return self.final_equity - self.initial_equity


def build_report(symbol: str, result: BacktestResult) -> BacktestReport:
    return BacktestReport(
        symbol=symbol,
        initial_equity=result.initial_equity,
        final_equity=result.final_equity,
        return_percent=result.total_return_percent,
        max_drawdown_percent=result.max_drawdown_percent,
        win_rate_percent=result.win_rate_percent,
        profit_factor=result.profit_factor,
        trades=len(result.trades),
        rejected_signals=result.rejected_signals,
        max_concurrent_positions=result.max_concurrent_positions,
    )


def build_portfolio_report(portfolio_result: Any) -> dict[str, Any]:
    """Serialize portfolio-level and per-symbol backtest results without floats."""
    results = getattr(portfolio_result, "results", {})
    return {
        "type": "portfolio_backtest",
        "initial_equity": str(portfolio_result.initial_equity),
        "final_equity": str(portfolio_result.final_equity),
        "net_pnl": str(portfolio_result.final_equity - portfolio_result.initial_equity),
        "return_percent": str(portfolio_result.total_return_percent),
        "max_drawdown_percent": str(portfolio_result.max_drawdown_percent),
        "total_trades": portfolio_result.total_trades,
        "symbols": {
            symbol: to_dict(build_report(symbol, result))
            for symbol, result in sorted(results.items())
        },
    }


def build_robustness_report(monte_carlo_result: Any) -> dict[str, Any]:
    return {
        "type": "monte_carlo_robustness",
        "simulations": monte_carlo_result.simulations,
        "initial_equity": str(monte_carlo_result.initial_equity),
        "median_final_equity": str(monte_carlo_result.median_final_equity),
        "worst_final_equity": str(monte_carlo_result.worst_final_equity),
        "best_final_equity": str(monte_carlo_result.best_final_equity),
        "median_return_percent": str(monte_carlo_result.median_return_percent),
        "worst_return_percent": str(monte_carlo_result.worst_return_percent),
        "best_return_percent": str(monte_carlo_result.best_return_percent),
        "median_max_drawdown_percent": str(monte_carlo_result.median_max_drawdown_percent),
        "worst_max_drawdown_percent": str(monte_carlo_result.worst_max_drawdown_percent),
    }


def to_dict(report: BacktestReport) -> dict[str, str | int | None]:
    return {
        "symbol": report.symbol,
        "initial_equity": str(report.initial_equity),
        "final_equity": str(report.final_equity),
        "net_pnl": str(report.net_pnl),
        "return_percent": str(report.return_percent),
        "max_drawdown_percent": str(report.max_drawdown_percent),
        "win_rate_percent": str(report.win_rate_percent),
        "profit_factor": None if report.profit_factor is None else str(report.profit_factor),
        "trades": report.trades,
        "rejected_signals": report.rejected_signals,
        "max_concurrent_positions": report.max_concurrent_positions,
    }
