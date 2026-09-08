from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.data.market_data import Candle, LivePrice


@dataclass(frozen=True)
class DataQuality:
    valid: bool
    reasons: tuple[str, ...] = ()


def validate_live_price(price: LivePrice, max_age_seconds: int = 120) -> DataQuality:
    reasons: list[str] = []
    now = datetime.now(timezone.utc)
    timestamp = price.timestamp.astimezone(timezone.utc)
    if price.price <= 0:
        reasons.append("price must be positive")
    if timestamp > now + timedelta(seconds=5):
        reasons.append("timestamp is in the future")
    if now - timestamp > timedelta(seconds=max_age_seconds):
        reasons.append("live price is stale")
    return DataQuality(not reasons, tuple(reasons))


def validate_candles(candles: tuple[Candle, ...]) -> DataQuality:
    reasons: list[str] = []
    if not candles:
        reasons.append("no candles")
        return DataQuality(False, tuple(reasons))
    previous = None
    for candle in candles:
        if candle.high < candle.low:
            reasons.append(f"high below low at {candle.timestamp.isoformat()}")
        if candle.open < candle.low or candle.open > candle.high:
            reasons.append(f"open outside range at {candle.timestamp.isoformat()}")
        if candle.close < candle.low or candle.close > candle.high:
            reasons.append(f"close outside range at {candle.timestamp.isoformat()}")
        if candle.volume < 0:
            reasons.append(f"negative volume at {candle.timestamp.isoformat()}")
        if previous and candle.timestamp <= previous:
            reasons.append("candles are not strictly chronological")
        previous = candle.timestamp
    return DataQuality(not reasons, tuple(reasons))
