from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import sqrt
from typing import Iterable

from app.journal.models import JournalEntry


@dataclass(frozen=True)
class RiskAnalyticsReport:
    max_drawdown: Decimal
    recovery_factor: Decimal | None
    average_holding_seconds: Decimal
    total_risk: Decimal
    realized_r_multiple: Decimal | None
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    calmar_ratio: Decimal | None


def _equity_curve(entries: Iterable[JournalEntry], starting_equity: Decimal) -> list[Decimal]:
    equity = starting_equity
    curve = [equity]
    for entry in sorted(entries, key=lambda item: (item.closed_at, item.position_id)):
        equity += entry.realized_pnl
        curve.append(equity)
    return curve


def _ratios(returns: list[Decimal]) -> tuple[Decimal | None, Decimal | None]:
    if len(returns) < 2:
        return None, None
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum(((item - mean) ** 2 for item in returns), Decimal("0")) / Decimal(len(returns) - 1)
    std = Decimal(str(sqrt(float(variance))))
    downside = [item for item in returns if item < 0]
    downside_std = None
    if downside:
        downside_mean = sum(downside, Decimal("0")) / Decimal(len(downside))
        downside_variance = sum(((item - downside_mean) ** 2 for item in downside), Decimal("0")) / Decimal(len(downside))
        downside_std = Decimal(str(sqrt(float(downside_variance))))
    sharpe = mean / std if std > 0 else None
    sortino = mean / downside_std if downside_std and downside_std > 0 else None
    return sharpe, sortino


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

    returns = [
        row.realized_pnl / starting_equity
        for row in rows
        if starting_equity > 0
    ]
    sharpe, sortino = _ratios(returns)

    net = sum((row.realized_pnl for row in rows), Decimal("0"))
    recovery = net / max_drawdown if max_drawdown > 0 else None
    calmar = net / max_drawdown if max_drawdown > 0 else None

    durations = [
        Decimal((row.closed_at - row.opened_at).total_seconds())
        for row in rows
        if row.opened_at is not None
    ]

    r_values = [
        row.realized_r_multiple
        for row in rows
        if row.realized_r_multiple is not None
    ]

    return RiskAnalyticsReport(
        max_drawdown=max_drawdown,
        recovery_factor=recovery,
        average_holding_seconds=(
            sum(durations, Decimal("0")) / Decimal(len(durations))
            if durations else Decimal("0")
        ),
        total_risk=sum((abs(row.realized_pnl) for row in rows), Decimal("0")),
        realized_r_multiple=(
            sum(r_values, Decimal("0")) / Decimal(len(r_values))
            if r_values else None
        ),
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
    )
