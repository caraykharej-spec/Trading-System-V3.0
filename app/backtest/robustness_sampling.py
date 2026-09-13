from __future__ import annotations

import random
from decimal import Decimal
from enum import Enum


class SamplingMode(str, Enum):
    RANDOM_PERMUTATION = "RANDOM_PERMUTATION"
    REVERSE = "REVERSE"
    WORST_FIRST = "WORST_FIRST"
    LOSS_CLUSTER = "LOSS_CLUSTER"
    WIN_CLUSTER = "WIN_CLUSTER"
    IID_BOOTSTRAP = "IID_BOOTSTRAP"
    BLOCK_BOOTSTRAP = "BLOCK_BOOTSTRAP"


def sample_pnl_path(
    pnl: tuple[Decimal, ...],
    *,
    mode: SamplingMode,
    seed: int,
    block_size: int = 5,
) -> tuple[Decimal, ...]:
    if not pnl:
        raise ValueError("PnL path must be non-empty")
    if seed < 0:
        raise ValueError("seed must be non-negative")
    if block_size < 1:
        raise ValueError("block_size must be positive")
    if any(not value.is_finite() for value in pnl):
        raise ValueError("PnL values must be finite")
    rng = random.Random(seed)
    values = list(pnl)

    if mode is SamplingMode.RANDOM_PERMUTATION:
        rng.shuffle(values)
        return tuple(values)
    if mode is SamplingMode.REVERSE:
        return tuple(reversed(values))
    if mode is SamplingMode.WORST_FIRST:
        return tuple(sorted(values))
    if mode is SamplingMode.LOSS_CLUSTER:
        return tuple(
            sorted(values, key=lambda value: (value >= 0, value))
        )
    if mode is SamplingMode.WIN_CLUSTER:
        return tuple(
            sorted(values, key=lambda value: (value < 0, -value))
        )
    if mode is SamplingMode.IID_BOOTSTRAP:
        return tuple(values[rng.randrange(len(values))] for _ in values)

    size = min(block_size, len(values))
    sampled: list[Decimal] = []
    while len(sampled) < len(values):
        start = rng.randrange(len(values) - size + 1)
        sampled.extend(values[start : start + size])
    return tuple(sampled[: len(values)])


def maximum_drawdown_percent(
    pnl: tuple[Decimal, ...],
    *,
    initial_equity: Decimal,
) -> Decimal:
    if initial_equity <= 0 or not initial_equity.is_finite():
        raise ValueError("initial_equity must be finite and positive")
    equity = initial_equity
    peak = initial_equity
    drawdown = Decimal("0")
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        if peak > 0:
            drawdown = max(
                drawdown,
                (peak - max(Decimal("0"), equity)) / peak * Decimal("100"),
            )
    return drawdown
