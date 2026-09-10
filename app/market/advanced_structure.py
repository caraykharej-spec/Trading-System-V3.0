from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.data.market_data import Candle


@dataclass(frozen=True)
class SwingPoint:
    kind: str
    timestamp: datetime
    price: Decimal
    index: int


@dataclass(frozen=True)
class StructureBreak:
    direction: str
    kind: str
    level: Decimal
    timestamp: datetime


@dataclass(frozen=True)
class AdvancedStructureResult:
    swing_highs: tuple[SwingPoint, ...]
    swing_lows: tuple[SwingPoint, ...]
    trend: str
    structure: str
    last_break: StructureBreak | None
    support: Decimal | None
    resistance: Decimal | None
    score: Decimal


def _validate(candles: list[Candle], pivot: int) -> list[Candle]:
    if pivot < 1:
        raise ValueError("pivot must be >= 1")
    ordered = sorted(candles, key=lambda c: c.timestamp)
    if any(ordered[i].timestamp == ordered[i - 1].timestamp for i in range(1, len(ordered))):
        raise ValueError("duplicate candle timestamps")
    return ordered


def detect_swings(candles: list[Candle], pivot: int = 2) -> tuple[tuple[SwingPoint, ...], tuple[SwingPoint, ...]]:
    ordered = _validate(candles, pivot)
    highs: list[SwingPoint] = []
    lows: list[SwingPoint] = []
    for i in range(pivot, len(ordered) - pivot):
        current = ordered[i]
        left = ordered[i - pivot:i]
        right = ordered[i + 1:i + pivot + 1]
        if current.high > max(c.high for c in left) and current.high >= max(c.high for c in right):
            highs.append(SwingPoint("HIGH", current.timestamp, current.high, i))
        if current.low < min(c.low for c in left) and current.low <= min(c.low for c in right):
            lows.append(SwingPoint("LOW", current.timestamp, current.low, i))
    return tuple(highs), tuple(lows)


def _sequence_trend(highs: tuple[SwingPoint, ...], lows: tuple[SwingPoint, ...]) -> str:
    if len(highs) < 2 or len(lows) < 2:
        return "UNKNOWN"
    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price
    if hh and hl:
        return "BULLISH"
    if lh and ll:
        return "BEARISH"
    return "TRANSITION"


def analyze_advanced_structure(candles: list[Candle], pivot: int = 2) -> AdvancedStructureResult:
    ordered = _validate(candles, pivot)
    highs, lows = detect_swings(ordered, pivot)
    trend = _sequence_trend(highs, lows)
    if not highs or not lows:
        return AdvancedStructureResult(highs, lows, trend, "UNKNOWN", None, lows[-1].price if lows else None, highs[-1].price if highs else None, Decimal("0"))
    last_close = ordered[-1].close
    last_high = highs[-1]
    last_low = lows[-1]
    break_event: StructureBreak | None = None
    structure = "RANGE"
    if last_close > last_high.price:
        kind = "BOS" if trend == "BULLISH" else "CHOCH"
        break_event = StructureBreak("UP", kind, last_high.price, ordered[-1].timestamp)
        structure = kind
    elif last_close < last_low.price:
        kind = "BOS" if trend == "BEARISH" else "CHOCH"
        break_event = StructureBreak("DOWN", kind, last_low.price, ordered[-1].timestamp)
        structure = kind
    elif trend == "BULLISH":
        structure = "HIGHER_HIGH_HIGHER_LOW"
    elif trend == "BEARISH":
        structure = "LOWER_HIGH_LOWER_LOW"
    else:
        structure = "TRANSITION"
    score = Decimal("90") if structure == "BOS" else Decimal("85") if structure == "CHOCH" else Decimal("70") if trend in {"BULLISH", "BEARISH"} else Decimal("50")
    return AdvancedStructureResult(highs, lows, trend, structure, break_event, last_low.price, last_high.price, score)
