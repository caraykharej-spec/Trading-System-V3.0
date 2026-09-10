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


def _aligned(snapshot: IndicatorSnapshot, last: Decimal) -> str:
    if snapshot.ema20 is None or snapshot.ema50 is None or snapshot.ema200 is None:
        return "UNKNOWN"
    if last > snapshot.ema20 > snapshot.ema50 > snapshot.ema200:
        return "BULLISH"
    if last < snapshot.ema20 < snapshot.ema50 < snapshot.ema200:
        return "BEARISH"
    return "NEUTRAL"


def analyze_trend(candles: list[Candle]) -> TrendResult:
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    snapshot = build_snapshot(ordered)
    if not ordered:
        return TrendResult("UNKNOWN", "UNKNOWN", Decimal("0"), snapshot)

    direction = _aligned(snapshot, ordered[-1].close)
    if direction == "UNKNOWN":
        return TrendResult(direction, "UNKNOWN", Decimal("0"), snapshot)

    if direction == "NEUTRAL":
        return TrendResult(direction, "WEAK", Decimal("45"), snapshot)

    score = Decimal("60")
    bullish = direction == "BULLISH"

    if snapshot.rsi14 is not None:
        if (bullish and snapshot.rsi14 >= Decimal("50")) or (
            not bullish and snapshot.rsi14 <= Decimal("50")
        ):
            score += Decimal("10")

    if snapshot.macd_histogram is not None:
        if (bullish and snapshot.macd_histogram > 0) or (
            not bullish and snapshot.macd_histogram < 0
        ):
            score += Decimal("10")

    if snapshot.adx14 is not None:
        if snapshot.adx14 >= Decimal("25"):
            score += Decimal("10")
        elif snapshot.adx14 >= Decimal("18"):
            score += Decimal("5")

    if snapshot.supertrend_direction == direction:
        score += Decimal("5")

    if snapshot.vwap20 is not None:
        last = ordered[-1].close
        if (bullish and last >= snapshot.vwap20) or (not bullish and last <= snapshot.vwap20):
            score += Decimal("5")

    score = min(score, Decimal("100"))
    strength = "STRONG" if score >= 85 else "MODERATE" if score >= 65 else "WEAK"
    return TrendResult(direction, strength, score, snapshot)
