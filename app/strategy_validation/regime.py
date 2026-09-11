from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.backtest.models import TradeRecord


@dataclass(frozen=True)
class RegimeInterval:
    label: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("regime label cannot be blank")
        if self.end < self.start:
            raise ValueError("regime interval end cannot precede start")


@dataclass(frozen=True)
class RegimePerformance:
    label: str
    trade_count: int
    total_pnl: Decimal
    win_rate_percent: Decimal
    profit_factor: Decimal | None


@dataclass(frozen=True)
class RegimeValidationReport:
    regimes: tuple[RegimePerformance, ...]

    def qualified_regime_count(
        self,
        *,
        min_trades: int,
        min_profit_factor: Decimal,
    ) -> int:
        return sum(
            1
            for item in self.regimes
            if item.trade_count >= min_trades
            and item.profit_factor is not None
            and item.profit_factor >= min_profit_factor
        )


def _label_for_trade(trade: TradeRecord, intervals: tuple[RegimeInterval, ...]) -> str:
    for interval in intervals:
        if interval.start <= trade.entry_time <= interval.end:
            return interval.label
    return "UNCLASSIFIED"


def _profit_factor(trades: list[TradeRecord]) -> Decimal | None:
    gains = sum(
        (trade.realized_pnl for trade in trades if trade.realized_pnl > 0),
        Decimal("0"),
    )
    losses = -sum(
        (trade.realized_pnl for trade in trades if trade.realized_pnl < 0),
        Decimal("0"),
    )
    if losses == 0:
        return None if gains == 0 else Decimal("999999")
    return gains / losses


def analyze_regime_performance(
    trades: tuple[TradeRecord, ...],
    intervals: tuple[RegimeInterval, ...],
) -> RegimeValidationReport:
    groups: dict[str, list[TradeRecord]] = {}
    for trade in trades:
        groups.setdefault(_label_for_trade(trade, intervals), []).append(trade)

    results: list[RegimePerformance] = []
    for label in sorted(groups):
        group = groups[label]
        wins = sum(1 for trade in group if trade.realized_pnl > 0)
        win_rate = Decimal(wins) / Decimal(len(group)) * Decimal("100")
        results.append(
            RegimePerformance(
                label=label,
                trade_count=len(group),
                total_pnl=sum((trade.realized_pnl for trade in group), Decimal("0")),
                win_rate_percent=win_rate,
                profit_factor=_profit_factor(group),
            )
        )
    return RegimeValidationReport(regimes=tuple(results))
