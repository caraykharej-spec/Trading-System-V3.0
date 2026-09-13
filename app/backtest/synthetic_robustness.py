from __future__ import annotations

import math
import random
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class SyntheticPathModel(str, Enum):
    GBM = "GBM"
    JUMP_DIFFUSION = "JUMP_DIFFUSION"
    VOLATILITY_CLUSTER = "VOLATILITY_CLUSTER"
    REGIME_SWITCHING = "REGIME_SWITCHING"


@dataclass(frozen=True)
class SyntheticPathConfig:
    steps: int
    seed: int
    drift: Decimal = Decimal("0")
    volatility: Decimal = Decimal("0.02")
    jump_probability: Decimal = Decimal("0.01")
    jump_scale: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        values = (
            self.drift,
            self.volatility,
            self.jump_probability,
            self.jump_scale,
        )
        if any(not value.is_finite() for value in values):
            raise ValueError("synthetic path parameters must be finite")
        if self.steps < 1 or self.seed < 0:
            raise ValueError("steps must be positive and seed non-negative")
        if self.volatility < 0 or self.jump_scale < 0:
            raise ValueError("volatility and jump scale must be non-negative")
        if not Decimal("0") <= self.jump_probability <= 1:
            raise ValueError("jump_probability must be in [0, 1]")


def generate_price_path(
    initial_price: Decimal,
    *,
    model: SyntheticPathModel,
    config: SyntheticPathConfig,
) -> tuple[Decimal, ...]:
    if not initial_price.is_finite() or initial_price <= 0:
        raise ValueError("initial_price must be finite and positive")
    rng = random.Random(config.seed)
    price = float(initial_price)
    drift = float(config.drift)
    base_volatility = float(config.volatility)
    prices = [initial_price]
    regime_sign = 1.0
    volatility = base_volatility

    for index in range(config.steps):
        if model is SyntheticPathModel.REGIME_SWITCHING and index and index % 25 == 0:
            regime_sign *= -1.0
        if model is SyntheticPathModel.VOLATILITY_CLUSTER:
            volatility = max(
                base_volatility * 0.25,
                0.85 * volatility + 0.15 * abs(rng.gauss(0, base_volatility)),
            )
        else:
            volatility = base_volatility
        shock = rng.gauss(0, volatility)
        step_drift = drift * regime_sign
        if (
            model is SyntheticPathModel.JUMP_DIFFUSION
            and rng.random() < float(config.jump_probability)
        ):
            shock += rng.gauss(0, float(config.jump_scale))
        price *= math.exp(step_drift - 0.5 * volatility**2 + shock)
        if not math.isfinite(price) or price <= 0:
            raise ValueError("synthetic path became non-finite")
        prices.append(Decimal(str(price)))
    return tuple(prices)


def inject_relative_noise(
    prices: tuple[Decimal, ...],
    *,
    maximum_absolute_percent: Decimal,
    seed: int,
) -> tuple[Decimal, ...]:
    if not prices:
        raise ValueError("price path must be non-empty")
    if (
        not maximum_absolute_percent.is_finite()
        or maximum_absolute_percent < 0
        or maximum_absolute_percent >= Decimal("100")
        or seed < 0
    ):
        raise ValueError("noise parameters are invalid")
    if any(not value.is_finite() or value <= 0 for value in prices):
        raise ValueError("prices must be finite and positive")
    rng = random.Random(seed)
    bound = float(maximum_absolute_percent / Decimal("100"))
    noisy = []
    for price in prices:
        multiplier = 1 + rng.uniform(-bound, bound)
        perturbed = price * Decimal(str(multiplier))
        if perturbed <= 0:
            raise ValueError("noise bound produced a non-positive price")
        noisy.append(perturbed)
    return tuple(noisy)


def corrupt_series_for_quality_test(
    values: tuple[Decimal, ...],
    *,
    duplicate_index: int | None = None,
    remove_index: int | None = None,
) -> tuple[Decimal, ...]:
    if duplicate_index is not None and remove_index is not None:
        raise ValueError("apply one data corruption per scenario")
    items = list(values)
    if duplicate_index is not None:
        if not 0 <= duplicate_index < len(items):
            raise IndexError("duplicate index outside series")
        items.insert(duplicate_index, items[duplicate_index])
    if remove_index is not None:
        if not 0 <= remove_index < len(items):
            raise IndexError("remove index outside series")
        items.pop(remove_index)
    return tuple(items)
