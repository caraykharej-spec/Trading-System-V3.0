from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.data.market_data import Candle, LivePrice


TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}
DEFAULT_CANDLE_MAX_AGE_SECONDS: dict[str, int] = {
    "1m": 180,
    "5m": 900,
    "15m": 2700,
    "30m": 5400,
    "1h": 10800,
    "2h": 21600,
    "4h": 43200,
    "1d": 259200,
}


@dataclass(frozen=True)
class DataQuality:
    valid: bool
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if not self.valid:
            return "INVALID"
        if self.warnings:
            return "DEGRADED"
        return "VALID"

    def merge(self, other: "DataQuality") -> "DataQuality":
        return DataQuality(
            self.valid and other.valid,
            self.reasons + other.reasons,
            self.warnings + other.warnings,
        )


def timeframe_seconds(timeframe: str) -> int:
    try:
        return TIMEFRAME_SECONDS[timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported timeframe: {timeframe}") from exc


def default_candle_max_age_seconds(timeframe: str) -> int:
    try:
        return DEFAULT_CANDLE_MAX_AGE_SECONDS[timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported timeframe: {timeframe}") from exc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def validate_live_price(
    price: LivePrice,
    max_age_seconds: int = 120,
    now: datetime | None = None,
    future_tolerance_seconds: int = 5,
) -> DataQuality:
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")
    reasons: list[str] = []
    try:
        timestamp = _utc(price.as_of)
    except ValueError as exc:
        return DataQuality(False, (str(exc),))
    current = _utc(now or datetime.now(timezone.utc))
    if not price.symbol:
        reasons.append("symbol is empty")
    if not price.provider:
        reasons.append("provider is empty")
    if not price.price.is_finite() or price.price <= 0:
        reasons.append("price must be finite and positive")
    if timestamp > current + timedelta(seconds=future_tolerance_seconds):
        reasons.append("timestamp is in the future")
    if current - timestamp > timedelta(seconds=max_age_seconds):
        reasons.append("live price is stale")
    return DataQuality(not reasons, tuple(reasons))


def validate_candles(
    candles: tuple[Candle, ...] | list[Candle],
    *,
    expected_timeframe: str | None = None,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
    require_complete_last_candle: bool = False,
) -> DataQuality:
    reasons: list[str] = []
    warnings: list[str] = []
    items = tuple(candles)
    if not items:
        return DataQuality(False, ("no candles",))
    if expected_timeframe is not None:
        try:
            step = timeframe_seconds(expected_timeframe)
        except ValueError as exc:
            return DataQuality(False, (str(exc),))
    else:
        step = timeframe_seconds(items[0].timeframe) if items[0].timeframe in TIMEFRAME_SECONDS else None

    previous: Candle | None = None
    for candle in items:
        if candle.timeframe not in TIMEFRAME_SECONDS:
            reasons.append(f"unsupported timeframe at {candle.timestamp.isoformat()}")
        if expected_timeframe and candle.timeframe != expected_timeframe:
            reasons.append(f"unexpected timeframe {candle.timeframe}; expected {expected_timeframe}")
        try:
            timestamp = _utc(candle.timestamp)
        except ValueError as exc:
            reasons.append(str(exc))
            continue
        values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
        if any(not value.is_finite() for value in values):
            reasons.append(f"non-finite OHLCV at {timestamp.isoformat()}")
        if candle.high < candle.low:
            reasons.append(f"high below low at {timestamp.isoformat()}")
        if candle.open < candle.low or candle.open > candle.high:
            reasons.append(f"open outside range at {timestamp.isoformat()}")
        if candle.close < candle.low or candle.close > candle.high:
            reasons.append(f"close outside range at {timestamp.isoformat()}")
        if candle.volume < 0:
            reasons.append(f"negative volume at {timestamp.isoformat()}")
        if previous is not None:
            delta = (timestamp - _utc(previous.timestamp)).total_seconds()
            if delta <= 0:
                reasons.append("candles are not strictly chronological")
            elif step is not None and delta != step:
                if delta > step:
                    reasons.append(
                        f"candle gap detected: {int(delta / step) - 1} missing interval(s) before {timestamp.isoformat()}"
                    )
                else:
                    reasons.append(f"candle spacing is shorter than timeframe at {timestamp.isoformat()}")
        previous = candle

    if max_age_seconds is not None:
        current = _utc(now or datetime.now(timezone.utc))
        age = (current - _utc(items[-1].timestamp)).total_seconds()
        if age < -5:
            reasons.append("latest candle timestamp is in the future")
        elif age > max_age_seconds:
            reasons.append("candle series is stale")

    if require_complete_last_candle and step is not None:
        current = _utc(now or datetime.now(timezone.utc))
        last = _utc(items[-1].timestamp)
        if current < last + timedelta(seconds=step):
            reasons.append("last candle is incomplete")

    return DataQuality(not reasons, tuple(reasons), tuple(warnings))


def detect_price_outliers(
    candles: tuple[Candle, ...] | list[Candle],
    *,
    max_return: Decimal = Decimal("0.50"),
    max_range: Decimal = Decimal("1.00"),
) -> DataQuality:
    if max_return <= 0 or max_range <= 0:
        raise ValueError("outlier thresholds must be positive")
    reasons: list[str] = []
    previous_close: Decimal | None = None
    for candle in candles:
        if candle.close <= 0 or candle.low <= 0:
            reasons.append(f"non-positive price at {candle.timestamp.isoformat()}")
            previous_close = candle.close
            continue
        candle_range = (candle.high - candle.low) / candle.low
        if candle_range > max_range:
            reasons.append(f"extreme candle range at {candle.timestamp.isoformat()}")
        if previous_close and previous_close > 0:
            move = abs(candle.close - previous_close) / previous_close
            if move > max_return:
                reasons.append(f"extreme close-to-close move at {candle.timestamp.isoformat()}")
        previous_close = candle.close
    return DataQuality(not reasons, tuple(reasons))


def detect_volume_anomalies(
    candles: tuple[Candle, ...] | list[Candle],
    *,
    multiplier: Decimal = Decimal("100"),
) -> DataQuality:
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    positive = [c.volume for c in candles if c.volume > 0 and c.volume.is_finite()]
    if len(positive) < 2:
        return DataQuality(True, (), ("insufficient positive volume history for anomaly detection",))
    baseline = sum(positive[:-1], Decimal("0")) / Decimal(len(positive) - 1)
    if baseline <= 0:
        return DataQuality(True, (), ("zero volume baseline",))
    if positive[-1] > baseline * multiplier:
        return DataQuality(True, (), ("latest volume is an extreme outlier",))
    return DataQuality(True)
