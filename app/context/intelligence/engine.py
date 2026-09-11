from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
from typing import Iterable, Mapping

from app.context.context_engine import ContextEngine
from app.context.models import EconomicEvent, NewsItem
from app.universe.instrument import Instrument

from .classification import RuleBasedIntelligenceClassifier
from .deduplication import deduplicate_news
from .macro import enrich_macro_events
from .models import (
    IntelligenceContextAssessment,
    IntelligenceSnapshot,
    NewsIntelligence,
    RawNewsRecord,
)
from .normalization import normalize_record
from .relevance import EntityResolver


class MarketIntelligenceEngine:
    """Normalizes and enriches context evidence without bypassing ContextEngine policy."""

    def __init__(
        self,
        *,
        entity_resolver: EntityResolver | None = None,
        classifier: RuleBasedIntelligenceClassifier | None = None,
        context_engine: ContextEngine | None = None,
    ) -> None:
        self.entity_resolver = entity_resolver or EntityResolver()
        self.classifier = classifier or RuleBasedIntelligenceClassifier()
        self.context_engine = context_engine or ContextEngine()

    def process(
        self,
        raw_news: Iterable[RawNewsRecord],
        events: Iterable[EconomicEvent],
        instruments: Iterable[Instrument],
    ) -> IntelligenceSnapshot:
        universe = tuple(instruments)
        normalized = [normalize_record(item) for item in raw_news]
        unique = deduplicate_news(normalized)
        intelligence: list[NewsIntelligence] = []
        news_items: list[NewsItem] = []

        for record in unique:
            relevance = self.entity_resolver.resolve(record, universe)
            classification = self.classifier.classify(record, relevance)
            key_material = f"{record.normalized_title}|{record.published_at.isoformat()}"
            canonical_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
            enriched = NewsIntelligence(
                canonical_key=canonical_key,
                title=record.title,
                published_at=record.published_at,
                sources=record.sources,
                symbols=relevance.symbols,
                entities=relevance.entities,
                category=classification.category,
                impact=classification.impact,
                confidence=classification.confidence,
                relevance=relevance.score,
                raw_ids=record.raw_ids,
                url=record.url,
                country=record.country,
            )
            intelligence.append(enriched)
            targets: tuple[str | None, ...] = relevance.symbols or (None,)
            for symbol in targets:
                news_items.append(
                    NewsItem(
                        item_id=f"{canonical_key}:{symbol or 'GLOBAL'}",
                        title=record.title,
                        published_at=record.published_at,
                        source=",".join(record.sources),
                        symbol=symbol,
                        impact=classification.impact,
                        country=record.country,
                    )
                )

        event_intelligence = enrich_macro_events(events, universe)
        return IntelligenceSnapshot(
            intelligence=tuple(intelligence),
            news_items=tuple(news_items),
            events=tuple(item.event for item in event_intelligence),
            event_intelligence=event_intelligence,
        )

    def assess(
        self,
        symbol: str,
        snapshot: IntelligenceSnapshot,
        *,
        now: datetime | None = None,
    ) -> IntelligenceContextAssessment:
        context = self.context_engine.assess(
            symbol,
            news=snapshot.news_items,
            events=snapshot.events,
            now=now,
        )
        relevant = [item for item in snapshot.intelligence if not item.symbols or symbol in item.symbols]
        confidence = (
            sum((item.confidence for item in relevant), Decimal("0")) / Decimal(len(relevant))
            if relevant
            else Decimal("0")
        )
        return IntelligenceContextAssessment(
            context=context,
            intelligence_confidence=confidence,
            relevant_items=len(relevant),
        )
