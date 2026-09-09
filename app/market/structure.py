from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.market_data import Candle


@dataclass(frozen=True)
class StructureResult:
    state: str
    support: Decimal | None
    resistance: Decimal | None
    score: Decimal


def analyze_structure(candles: list[Candle], lookback: int = 20) -> StructureResult:
    ordered = sorted(candles, key=lambda x: x.timestamp)
    if len(ordered) < lookback:
        return StructureResult("UNKNOWN", None, None, Decimal("0"))
    window = ordered[-lookback:]
    support = min(c.low for c in window)
    resistance = max(c.high for c in window)
    last = window[-1].close
    if last > resistance:
        state = "BREAKOUT_UP"
    elif last < support:
        state = "BREAKOUT_DOWN"
    elif last >= resistance * Decimal("0.995"):
        state = "NEAR_RESISTANCE"
    elif last <= support * Decimal("1.005"):
        state = "NEAR_SUPPORT"
    else:
        state = "RANGE"
    score = Decimal("70") if state.startswith("BREAKOUT") else Decimal("50")
    return StructureResult(state, support, resistance, score)
