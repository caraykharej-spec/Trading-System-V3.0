from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.journal.models import JournalEntry


@dataclass(frozen=True)
class RiskAnalyticsReport:
    max_drawdown: Decimal
    recovery_factor: Decimal
    profit_factor: Decimal | None
    expectancy_r: Decimal | None
    average_hold_seconds: Decimal
    largest_win: Decimal | None
    largest_loss: Decimal | None


def analyze_risk_performance(
    entries: Iterable[JournalEntry],
) -> RiskAnalyticsReport:
    rows = sorted(entries, key=lambda e: (e.closed_at, e.position_id))
    equity = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    profits = Decimal("0")
    losses = Decimal("0")
    holds: list[Decimal] = []
    r_values: list[Decimal] = []

    for entry in rows:
        equity += entry.realized_pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if entry.realized_pnl > 0:
            profits += entry.realized_pnl
        elif entry.realized_pnl < 0:
            losses += -entry.realized_pnl
        if entry.realized_r_multiple is not None:
            r_values.append(entry.realized_r_multiple)
        if entry.opened_at is not None:
            holds.append(Decimal(str((entry.closed_at - entry.opened_at).total_seconds())))

    net = equity
    return RiskAnalyticsReport(
        max_drawdown=max_drawdown,
        recovery_factor=net / max_drawdown if max_drawdown else Decimal("0"),
        profit_factor=profits / losses if losses else None,
        expectancy_r=(sum(r_values, Decimal("0")) / Decimal(len(r_values))) if r_values else None,
        average_hold_seconds=(sum(holds, Decimal("0")) / Decimal(len(holds))) if holds else Decimal("0"),
        largest_win=max((e.realized_pnl for e in rows if e.realized_pnl > 0), default=None),
        largest_loss=min((e.realized_pnl for e in rows if e.realized_pnl < 0), default=None),
    )
