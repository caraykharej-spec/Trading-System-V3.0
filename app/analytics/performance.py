from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.journal.models import JournalEntry


@dataclass(frozen=True)
class PerformanceReport:
    total_trades: int
    wins: int
    losses: int
    breakeven: int
    gross_profit: Decimal
    gross_loss: Decimal
    net_pnl: Decimal
    win_rate_percent: Decimal
    average_pnl: Decimal
    average_win: Decimal
    average_loss: Decimal
    profit_factor: Decimal | None
    expectancy: Decimal
    max_consecutive_losses: int
    best_trade: Decimal | None
    worst_trade: Decimal | None


def analyze_performance(entries: Iterable[JournalEntry]) -> PerformanceReport:
    rows = sorted(entries, key=lambda entry: (entry.closed_at, entry.position_id))
    pnls = [entry.realized_pnl for entry in rows]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    breakeven = len(pnls) - len(wins) - len(losses)
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = sum((-pnl for pnl in losses), Decimal("0"))
    net_pnl = gross_profit - gross_loss
    total = len(pnls)

    if total:
        win_rate = Decimal(len(wins)) / Decimal(total) * Decimal("100")
        average_pnl = net_pnl / Decimal(total)
    else:
        win_rate = Decimal("0")
        average_pnl = Decimal("0")

    average_win = gross_profit / Decimal(len(wins)) if wins else Decimal("0")
    average_loss = -gross_loss / Decimal(len(losses)) if losses else Decimal("0")
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    if total:
        win_probability = Decimal(len(wins)) / Decimal(total)
        loss_probability = Decimal(len(losses)) / Decimal(total)
        expectancy = win_probability * average_win + loss_probability * average_loss
    else:
        expectancy = Decimal("0")

    max_loss_streak = current_loss_streak = 0
    for pnl in pnls:
        if pnl < 0:
            current_loss_streak += 1
            max_loss_streak = max(max_loss_streak, current_loss_streak)
        else:
            current_loss_streak = 0

    return PerformanceReport(
        total_trades=total,
        wins=len(wins),
        losses=len(losses),
        breakeven=breakeven,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=net_pnl,
        win_rate_percent=win_rate,
        average_pnl=average_pnl,
        average_win=average_win,
        average_loss=average_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_consecutive_losses=max_loss_streak,
        best_trade=max(pnls) if pnls else None,
        worst_trade=min(pnls) if pnls else None,
    )
