from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.journal.models import JournalEntry


@dataclass(frozen=True)
class RiskAnalyticsReport:
    max_drawdown: Decimal
    recovery_factor: Decimal | None
    average_holding_seconds: Decimal
    total_risk: Decimal
    realized_r_multiple: Decimal | None


def _equity_curve(entries: Iterable[JournalEntry], starting_equity: Decimal) -> list[Decimal]:
    equity = starting_equity
    curve = [equity]
    for entry in sorted(entries, key=lambda item: (item.closed_at, item.position_id)):
        equity += entry.realized_pnl
        curve.append(equity)
    return curve


def analyze_risk_performance(
    entries: Iterable[JournalEntry], *, starting_equity: Decimal = Decimal("10000")
) -> RiskAnalyticsReport:
    rows = list(entries)
    curve = _equity_curve(rows, starting_equity)

    peak = curve[0]
    max_drawdown = Decimal("0")
    for value in curve:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)

    net = sum((row.realized_pnl for row in rows), Decimal("0"))
    recovery = net / max_drawdown if max_drawdown > 0 else None

    durations = [
        Decimal((row.closed_at - row.opened_at).total_seconds())
        for row in rows
        if row.opened_at is not None
    ]
    average_duration = (
        sum(durations, Decimal("0")) / Decimal(len(durations))
        if durations
        else Decimal("0")
    )

    r_values = [
        row.realized_r_multiple
        for row in rows
        if row.realized_r_multiple is not None
    ]

    return RiskAnalyticsReport(
        max_drawdown=max_drawdown,
        recovery_factor=recovery,
        average_holding_seconds=average_duration,
        total_risk=sum(
            (abs(row.realized_pnl) for row in rows), Decimal("0")
        ),
        realized_r_multiple=(
            sum(r_values, Decimal("0")) / Decimal(len(r_values))
            if r_values
            else None
        ),
    )
