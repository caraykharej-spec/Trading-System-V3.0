from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.market_data import Candle
from app.market.trend import TrendResult


@dataclass(frozen=True)
class RegimeResult:
    regime: str
    volatility: str
    score: Decimal


def classify_regime(candles: list[Candle], trend: TrendResult) -> RegimeResult:
    ordered = sorted(candles, key=lambda x: x.timestamp)
    if not ordered or trend.direction == "UNKNOWN":
        return RegimeResult("UNKNOWN", "UNKNOWN", Decimal("0"))
    last = ordered[-1].close
    ranges = [(c.high - c.low) / c.close for c in ordered[-20:] if c.close > 0]
    avg_range = sum(ranges) / Decimal(len(ranges)) if ranges else Decimal("0")
    if avg_range >= Decimal("0.03"):
        volatility = "HIGH"
    elif avg_range <= Decimal("0.01"):
        volatility = "LOW"
    else:
        volatility = "NORMAL"

    if trend.direction == "BULLISH":
        regime = "TRENDING_BULL"
    elif trend.direction == "BEARISH":
        regime = "TRENDING_BEAR"
    else:
        regime = "RANGING"
    score = trend.score
    if volatility == "HIGH":
        score = max(Decimal("0"), score - Decimal("10"))
    return RegimeResult(regime, volatility, score)
