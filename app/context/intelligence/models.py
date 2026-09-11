from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.context.models import ContextAssessment, EconomicEvent, NewsImpact, NewsItem


class IntelligenceCategory(str, Enum):
    MACRO = "MACRO"
    REGULATORY = "REGULATORY"
    SECURITY = "SECURITY"
    EXCHANGE = "EXCHANGE"
    PROTOCOL = "PROTOCOL"
    CORPORATE = "CORPORATE"
    MARKET_STRUCTURE = "MARKET_STRUCTURE"
    OTHER = "OTHER"


@dataclass(frozen=True)
class RawNewsRecord:
    raw_id: str
    title: str
    published_at: datetime
    source: str
    body: str = ""
    url: str | None = None
    symbol_hints: tuple[str, ...] = ()
    country: str | None = None

    def __post_init__(self) -> None:
        if not self.raw_id.strip() or not self.title.strip() or not self.source.strip():
            raise ValueError("raw_id, title and source are required")
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")


@dataclass(frozen=True)
class NormalizedNewsRecord:
    raw_ids: tuple[str, ...]
    title: str
    normalized_title: str
    published_at: datetime
    sources: tuple[str, ...]
    body: str = ""
    url: str | None = None
    symbol_hints: tuple[str, ...] = ()
    country: str | None = None


@dataclass(frozen=True)
class RelevanceResult:
    symbols: tuple[str, ...]
    entities: tuple[str, ...]
    score: Decimal

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.score <= Decimal("1"):
            raise ValueError("relevance score must be in [0, 1]")


@dataclass(frozen=True)
class ClassificationResult:
    category: IntelligenceCategory
    impact: NewsImpact
    confidence: Decimal

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be in [0, 1]")


@dataclass(frozen=True)
class NewsIntelligence:
    canonical_key: str
    title: str
    published_at: datetime
    sources: tuple[str, ...]
    symbols: tuple[str, ...]
    entities: tuple[str, ...]
    category: IntelligenceCategory
    impact: NewsImpact
    confidence: Decimal
    relevance: Decimal
    raw_ids: tuple[str, ...]
    url: str | None = None
    country: str | None = None

    def __post_init__(self) -> None:
        for name, value in (("confidence", self.confidence), ("relevance", self.relevance)):
            if not Decimal("0") <= value <= Decimal("1"):
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class EventIntelligence:
    event: EconomicEvent
    category: IntelligenceCategory
    confidence: Decimal

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be in [0, 1]")


@dataclass(frozen=True)
class IntelligenceSnapshot:
    intelligence: tuple[NewsIntelligence, ...]
    news_items: tuple[NewsItem, ...]
    events: tuple[EconomicEvent, ...]
    event_intelligence: tuple[EventIntelligence, ...]


@dataclass(frozen=True)
class IntelligenceContextAssessment:
    context: ContextAssessment
    intelligence_confidence: Decimal
    relevant_items: int

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.intelligence_confidence <= Decimal("1"):
            raise ValueError("intelligence_confidence must be in [0, 1]")
