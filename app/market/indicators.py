from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import mean

from app.data.market_data import Candle


@dataclass(frozen=True)
class IndicatorSnapshot:
    ema20: Decimal | None
    ema50: Decimal | None
    ema200: Decimal | None
    rsi14: Decimal | None
    atr14: Decimal | None
    volume_sma20: Decimal | None


def _closes(candles: list[Candle]) -> list[Decimal]:
    return [c.close for c in sorted(candles, key=lambda x: x.timestamp)]


def ema(values: list[Decimal], period: int) -> Decimal | None:
    if len(values) < period:
        return None
    multiplier = Decimal(2) / Decimal(period + 1)
    result = sum(values[:period]) / Decimal(period)
    for value in values[period:]:
        result = (value - result) * multiplier + result
    return result


def rsi(values: list[Decimal], period: int = 14) -> Decimal | None:
    if len(values) < period + 1:
        return None
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for previous, current in zip(values[-period - 1:-1], values[-period:]):
        change = current - previous
        gains.append(max(change, Decimal("0")))
        losses.append(max(-change, Decimal("0")))
    avg_gain = sum(gains) / Decimal(period)
    avg_loss = sum(losses) / Decimal(period)
    if avg_loss == 0:
        return Decimal("100") if avg_gain > 0 else Decimal("50")
    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def atr(candles: list[Candle], period: int = 14) -> Decimal | None:
    ordered = sorted(candles, key=lambda x: x.timestamp)
    if len(ordered) < period + 1:
        return None
    true_ranges: list[Decimal] = []
    for previous, current in zip(ordered[-period - 1:-1], ordered[-period:]):
        true_ranges.append(max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        ))
    return sum(true_ranges) / Decimal(period)


def build_snapshot(candles: list[Candle]) -> IndicatorSnapshot:
    ordered = sorted(candles, key=lambda x: x.timestamp)
    closes = _closes(ordered)
    volumes = [c.volume for c in ordered[-20:]]
    return IndicatorSnapshot(
        ema20=ema(closes, 20),
        ema50=ema(closes, 50),
        ema200=ema(closes, 200),
        rsi14=rsi(closes),
        atr14=atr(ordered),
        volume_sma20=Decimal(str(mean(volumes))) if len(volumes) == 20 else None,
    )
