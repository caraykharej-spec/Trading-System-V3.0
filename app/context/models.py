from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class NewsImpact(str, Enum):
    SUPPORTIVE = "SUPPORTIVE"
    NEUTRAL = "NEUTRAL"
    ADVERSE = "ADVERSE"
    UNKNOWN = "UNKNOWN"


class EventImportance(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class NewsItem:
    item_id: str
    title: str
    published_at: datetime
    source: str
    symbol: str | None = None
    impact: NewsImpact = NewsImpact.UNKNOWN
    country: str | None = None


@dataclass(frozen=True)
class EconomicEvent:
    event_id: str
    name: str
    event_time: datetime
    country: str
    importance: EventImportance
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    symbols: tuple[str, ...] = ()
    currency: str | None = None

    @property
    def surprise(self) -> float | None:
        if self.actual is None or self.forecast is None:
            return None
        return self.actual - self.forecast


@dataclass(frozen=True)
class ContextAssessment:
    news: NewsImpact
    event: EventImportance
    reasons: tuple[str, ...]
    blocking: bool
    delay: bool
    surprise: float | None = None

    @property
    def tradable(self) -> bool:
        return not self.blocking
