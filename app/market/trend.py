from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.market_data import Candle
from app.market.indicators import IndicatorSnapshot, build_snapshot


@dataclass(frozen=True)
class TrendResult:
    direction: str
    strength: str
    score: Decimal
    indicators: IndicatorSnapshot


def analyze_trend(candles: list[Candle]) -> TrendResult:
    snapshot = build_snapshot(candles)
    if snapshot.ema20 is None or snapshot.ema50 is None or snapshot.ema200 is None:
        return TrendResult("UNKNOWN", "UNKNOWN", Decimal("0"), snapshot)

    last = sorted(candles, key=lambda x: x.timestamp)[-1].close
    bullish = last > snapshot.ema20 > snapshot.ema50 > snapshot.ema200
    bearish = last < snapshot.ema20 < snapshot.ema50 < snapshot.ema200
    if bullish:
        direction = "BULLISH"
    elif bearish:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    score = Decimal("50")
    if direction == "BULLISH":
        score = Decimal("80")
    elif direction == "BEARISH":
        score = Decimal("80")
    if snapshot.rsi14 is not None:
        if direction == "BULLISH" and snapshot.rsi14 >= 50:
            score += Decimal("10")
        elif direction == "BEARISH" and snapshot.rsi14 <= 50:
            score += Decimal("10")
    score = min(score, Decimal("100"))
    strength = "STRONG" if score >= 85 else "MODERATE" if score >= 65 else "WEAK"
    return TrendResult(direction, strength, score, snapshot)
