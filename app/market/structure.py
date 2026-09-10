from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.market_data import Candle
from app.market.advanced_structure import analyze_advanced_structure


@dataclass(frozen=True)
class StructureResult:
    state: str
    support: Decimal | None
    resistance: Decimal | None
    score: Decimal


def analyze_structure(candles: list[Candle], lookback: int = 20) -> StructureResult:
    if lookback < 3:
        raise ValueError("lookback must be >= 3")
    ordered = sorted(candles, key=lambda x: x.timestamp)
    if len(ordered) < lookback:
        return StructureResult("UNKNOWN", None, None, Decimal("0"))
    result = analyze_advanced_structure(ordered[-lookback:], pivot=max(1, min(2, lookback // 4)))
    support, resistance = result.support, result.resistance
    last = ordered[-1].close
    if result.structure == "BOS":
        state = "BREAKOUT_UP" if result.last_break and result.last_break.direction == "UP" else "BREAKOUT_DOWN"
    elif result.structure == "CHOCH":
        state = "CHOCH_UP" if result.last_break and result.last_break.direction == "UP" else "CHOCH_DOWN"
    elif support is not None and last <= support * Decimal("1.005"):
        state = "NEAR_SUPPORT"
    elif resistance is not None and last >= resistance * Decimal("0.995"):
        state = "NEAR_RESISTANCE"
    elif result.trend == "BULLISH":
        state = "BULLISH_STRUCTURE"
    elif result.trend == "BEARISH":
        state = "BEARISH_STRUCTURE"
    elif result.trend == "TRANSITION":
        state = "TRANSITION"
    else:
        state = "RANGE"
    return StructureResult(state, support, resistance, result.score)
