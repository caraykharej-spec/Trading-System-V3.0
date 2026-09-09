from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

from .models import TradeRecord


@dataclass(frozen=True)
class MonteCarloResult:
    simulations: int
    initial_equity: Decimal
    median_final_equity: Decimal
    worst_final_equity: Decimal
    best_final_equity: Decimal
    median_return_percent: Decimal
    worst_return_percent: Decimal
    best_return_percent: Decimal
    median_max_drawdown_percent: Decimal
    worst_max_drawdown_percent: Decimal


def _simulate(
    trades: tuple[TradeRecord, ...],
    initial_equity: Decimal,
    rng: random.Random,
    bootstrap: bool = False,
    slippage_stress_percent: Decimal = Decimal("0"),
    commission_stress_multiplier: Decimal = Decimal("1"),
) -> tuple[Decimal, Decimal]:
    if bootstrap:
        sampled = [trades[rng.randrange(len(trades))] for _ in trades]
    else:
        sampled = list(trades)
        rng.shuffle(sampled)

    equity = initial_equity
    peak = equity
    max_dd = Decimal("0")
    stress = slippage_stress_percent / Decimal("100")

    for trade in sampled:
        pnl = trade.realized_pnl
        stress_cost = trade.total_amount * trade.leverage * stress * Decimal("2")
        commission = trade.commission * commission_stress_multiplier
        pnl -= stress_cost + max(Decimal("0"), commission - trade.commission)
        equity = max(Decimal("0"), equity + pnl)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * Decimal("100"))

    return equity, max_dd


def run_monte_carlo(
    trades: tuple[TradeRecord, ...],
    simulations: int = 1000,
    seed: int = 42,
    initial_equity: Decimal | None = None,
    bootstrap: bool = False,
    slippage_stress_percent: Decimal = Decimal("0"),
    commission_stress_multiplier: Decimal = Decimal("1"),
) -> MonteCarloResult:
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    if initial_equity is None:
        initial_equity = Decimal("10000")
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    if slippage_stress_percent < 0:
        raise ValueError("slippage_stress_percent must be non-negative")
    if commission_stress_multiplier < 0:
        raise ValueError("commission_stress_multiplier must be non-negative")
    if not trades:
        return MonteCarloResult(
            simulations, initial_equity, initial_equity, initial_equity, initial_equity,
            Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
        )

    rng = random.Random(seed)
    outcomes = [
        _simulate(trades, initial_equity, rng, bootstrap, slippage_stress_percent, commission_stress_multiplier)
        for _ in range(simulations)
    ]
    finals = sorted(x[0] for x in outcomes)
    drawdowns = sorted(x[1] for x in outcomes)
    returns = sorted((x[0] - initial_equity) / initial_equity * Decimal("100") for x in outcomes)
    mid = (simulations - 1) // 2
    return MonteCarloResult(
        simulations=simulations,
        initial_equity=initial_equity,
        median_final_equity=finals[mid],
        worst_final_equity=finals[0],
        best_final_equity=finals[-1],
        median_return_percent=returns[mid],
        worst_return_percent=returns[0],
        best_return_percent=returns[-1],
        median_max_drawdown_percent=drawdowns[mid],
        worst_max_drawdown_percent=drawdowns[-1],
    )
