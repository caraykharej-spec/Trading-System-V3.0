from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from app.data.candle_builder import timeframe_seconds
from app.data.market_data import Candle, LivePrice


class SLAStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    MISSING = "MISSING"


@dataclass(frozen=True)
class DataSLA:
    max_live_age_seconds: int = 30
    max_candle_intervals: float = 2.0
    degraded_ratio: float = 0.75

    def validate(self) -> None:
        if self.max_live_age_seconds <= 0:
            raise ValueError("max_live_age_seconds must be positive")
        if self.max_candle_intervals <= 0:
            raise ValueError("max_candle_intervals must be positive")
        if not 0 < self.degraded_ratio < 1:
            raise ValueError("degraded_ratio must be between 0 and 1")


@dataclass(frozen=True)
class SLAEvaluation:
    status: SLAStatus
    age_seconds: float | None
    limit_seconds: float

    @property
    def usable(self) -> bool:
        return self.status in {SLAStatus.HEALTHY, SLAStatus.DEGRADED}


class MarketDataSLAMonitor:
    def __init__(self, policy: DataSLA | None = None) -> None:
        self.policy = policy or DataSLA()
        self.policy.validate()

    def evaluate_live(
        self, price: LivePrice | None, *, now: datetime | None = None
    ) -> SLAEvaluation:
        return self._evaluate_timestamp(
            None if price is None else price.as_of,
            float(self.policy.max_live_age_seconds),
            now=now,
        )

    def evaluate_candle(
        self, candle: Candle | None, *, now: datetime | None = None
    ) -> SLAEvaluation:
        limit = float(timeframe_seconds(candle.timeframe)) * self.policy.max_candle_intervals if candle else 0.0
        return self._evaluate_timestamp(
            None if candle is None else candle.timestamp,
            limit,
            now=now,
        )

    def _evaluate_timestamp(
        self,
        timestamp: datetime | None,
        limit_seconds: float,
        *,
        now: datetime | None,
    ) -> SLAEvaluation:
        if timestamp is None:
            return SLAEvaluation(SLAStatus.MISSING, None, limit_seconds)
        current = now or datetime.now(timezone.utc)
        normalized = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)
        age = (current - normalized).total_seconds()
        if age < 0:
            return SLAEvaluation(SLAStatus.STALE, age, limit_seconds)
        if age > limit_seconds:
            return SLAEvaluation(SLAStatus.STALE, age, limit_seconds)
        if age > limit_seconds * self.policy.degraded_ratio:
            return SLAEvaluation(SLAStatus.DEGRADED, age, limit_seconds)
        return SLAEvaluation(SLAStatus.HEALTHY, age, limit_seconds)
