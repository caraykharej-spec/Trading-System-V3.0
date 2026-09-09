from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

from .models import TradeRecord


@dataclass(frozen=True)
class MonteCarloResult:
    simulations: int
    median_return_percent: Decimal
    worst_return_percent: Decimal
    best_return_percent: Decimal
    median_max_drawdown_percent: Decimal
    worst_max_drawdown_percent: Decimal


def _simulate(trades: tuple[TradeRecord, ...], rng: random.Random) -> tuple[Decimal, Decimal]:
    shuffled = list(trades)
    rng.shuffle(shuffled)
    equity = Decimal("100")
    peak = equity
    max_dd = Decimal("0")
    for trade in shuffled:
        equity += trade.realized_pnl / Decimal("100")
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak * Decimal("100")
            max_dd = max(max_dd, dd)
    return (equity - Decimal("100")), max_dd


def run_monte_carlo(trades: tuple[TradeRecord, ...], simulations: int = 1000, seed: int = 42) -> MonteCarloResult:
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    if not trades:
        return MonteCarloResult(simulations, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
    rng = random.Random(seed)
    outcomes = [_simulate(trades, rng) for _ in range(simulations)]
    returns = sorted(x[0] for x in outcomes)
    drawdowns = sorted(x[1] for x in outcomes)
    mid = simulations // 2
    return MonteCarloResult(
        simulations=simulations,
        median_return_percent=returns[mid],
        worst_return_percent=returns[0],
        best_return_percent=returns[-1],
        median_max_drawdown_percent=drawdowns[mid],
        worst_max_drawdown_percent=drawdowns[-1],
    )
