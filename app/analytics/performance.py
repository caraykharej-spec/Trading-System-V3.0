from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

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
    average_r_multiple: Decimal | None = None


@dataclass(frozen=True)
class EquityPoint:
    closed_at: str
    equity: Decimal


@dataclass(frozen=True)
class DetailedPerformanceReport:
    overall: PerformanceReport
    by_setup: dict[str, PerformanceReport]
    by_regime: dict[str, PerformanceReport]
    by_direction: dict[str, PerformanceReport]
    by_symbol: dict[str, PerformanceReport]
    by_month: dict[str, PerformanceReport]
    equity_curve: tuple[EquityPoint, ...]


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

    r_multiples = [
        value
        for entry in rows
        if (value := entry.realized_r_multiple) is not None
    ]
    average_r = (
        sum(r_multiples, Decimal("0")) / Decimal(len(r_multiples))
        if r_multiples
        else None
    )

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
        average_r_multiple=average_r,
    )


def _decision_value(entry: JournalEntry, key: str, fallback: str) -> str:
    value = entry.decision.get(key)
    return str(value) if value not in (None, "") else fallback


def _regime(entry: JournalEntry) -> str:
    quality = entry.decision.get("strategy_quality")
    regime = entry.decision.get("market_regime")
    if regime not in (None, ""):
        return str(regime)
    if isinstance(quality, dict):
        inferred = quality.get("regime")
        if inferred not in (None, ""):
            return str(inferred)
    return "UNKNOWN"


def _group(
    rows: list[JournalEntry], key: Callable[[JournalEntry], str]
) -> dict[str, PerformanceReport]:
    buckets: dict[str, list[JournalEntry]] = {}
    for entry in rows:
        buckets.setdefault(key(entry), []).append(entry)
    return {name: analyze_performance(items) for name, items in sorted(buckets.items())}


def analyze_detailed_performance(
    entries: Iterable[JournalEntry], *, starting_equity: Decimal = Decimal("10000")
) -> DetailedPerformanceReport:
    if starting_equity <= 0:
        raise ValueError("starting_equity must be positive")
    rows = sorted(entries, key=lambda entry: (entry.closed_at, entry.position_id))
    equity = starting_equity
    curve: list[EquityPoint] = []
    for entry in rows:
        equity += entry.realized_pnl
        curve.append(EquityPoint(entry.closed_at.isoformat(), equity))

    return DetailedPerformanceReport(
        overall=analyze_performance(rows),
        by_setup=_group(rows, lambda entry: _decision_value(entry, "setup", "UNKNOWN")),
        by_regime=_group(rows, _regime),
        by_direction=_group(rows, lambda entry: entry.side.value),
        by_symbol=_group(rows, lambda entry: entry.symbol),
        by_month=_group(rows, lambda entry: entry.closed_at.strftime("%Y-%m")),
        equity_curve=tuple(curve),
    )
