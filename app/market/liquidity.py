from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.market_data import Candle


@dataclass(frozen=True)
class LiquidityResult:
    average_volume: Decimal | None
    latest_volume: Decimal | None
    volume_ratio: Decimal | None
    score: Decimal


def analyze_liquidity(candles: list[Candle], period: int = 20) -> LiquidityResult:
    ordered = sorted(candles, key=lambda x: x.timestamp)
    if len(ordered) < period + 1:
        return LiquidityResult(None, None, None, Decimal("0"))
    baseline = sum(c.volume for c in ordered[-period - 1:-1]) / Decimal(period)
    latest = ordered[-1].volume
    if baseline <= 0:
        return LiquidityResult(baseline, latest, None, Decimal("0"))
    ratio = latest / baseline
    score = min(Decimal("100"), ratio * Decimal("50"))
    return LiquidityResult(baseline, latest, ratio, score)
