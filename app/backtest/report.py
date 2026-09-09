from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

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


def to_dict(report: BacktestReport) -> dict[str, str | int | None]:
    return {
        "symbol": report.symbol,
        "initial_equity": str(report.initial_equity),
        "final_equity": str(report.final_equity),
        "return_percent": str(report.return_percent),
        "max_drawdown_percent": str(report.max_drawdown_percent),
        "win_rate_percent": str(report.win_rate_percent),
        "profit_factor": None if report.profit_factor is None else str(report.profit_factor),
        "trades": report.trades,
        "rejected_signals": report.rejected_signals,
        "max_concurrent_positions": report.max_concurrent_positions,
    }
