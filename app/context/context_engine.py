from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.context.models import ContextAssessment, EconomicEvent, EventImportance, NewsImpact, NewsItem


@dataclass(frozen=True)
class ContextPolicy:
    critical_event_window: timedelta = timedelta(minutes=30)
    high_event_window: timedelta = timedelta(minutes=15)
    stale_news_after: timedelta = timedelta(hours=24)
    block_critical_events: bool = True
    delay_high_events: bool = True


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _event_active(event: EconomicEvent, now: datetime, window: timedelta) -> bool:
    return abs(_utc(event.event_time) - now) <= window


def _merge_news(items: Iterable[NewsItem], symbol: str, now: datetime, policy: ContextPolicy) -> tuple[NewsImpact, list[str]]:
    candidates = [item for item in items if item.symbol in (None, symbol) and now - policy.stale_news_after <= _utc(item.published_at) <= now]
    if not candidates:
        return NewsImpact.UNKNOWN, ["no_fresh_relevant_news"]
    if any(item.impact == NewsImpact.ADVERSE for item in candidates):
        return NewsImpact.ADVERSE, ["adverse_relevant_news"]
    if any(item.impact == NewsImpact.SUPPORTIVE for item in candidates):
        return NewsImpact.SUPPORTIVE, ["supportive_relevant_news"]
    if all(item.impact == NewsImpact.NEUTRAL for item in candidates):
        return NewsImpact.NEUTRAL, ["neutral_relevant_news"]
    return NewsImpact.UNKNOWN, ["mixed_or_unknown_news_impact"]


def _event_state(events: Iterable[EconomicEvent], symbol: str, now: datetime, policy: ContextPolicy) -> tuple[EventImportance, list[str]]:
    active = []
    for event in events:
        if not _event_active(event, now, policy.critical_event_window if event.importance == EventImportance.CRITICAL else policy.high_event_window if event.importance == EventImportance.HIGH else timedelta(0)):
            continue
        active.append(event)
    if any(event.importance == EventImportance.CRITICAL for event in active):
        return EventImportance.CRITICAL, ["critical_event_window_active"]
    if any(event.importance == EventImportance.HIGH for event in active):
        return EventImportance.HIGH, ["high_event_window_active"]
    if any(event.importance == EventImportance.MEDIUM for event in active):
        return EventImportance.MEDIUM, ["medium_event_active"]
    if any(event.importance == EventImportance.LOW for event in active):
        return EventImportance.LOW, ["low_event_active"]
    return EventImportance.NONE, ["no_high_impact_event_window"]


class ContextEngine:
    def __init__(self, policy: ContextPolicy = ContextPolicy()) -> None:
        self.policy = policy

    def assess(self, symbol: str, *, news: Iterable[NewsItem] = (), events: Iterable[EconomicEvent] = (), now: datetime | None = None) -> ContextAssessment:
        if not symbol:
            raise ValueError("symbol must not be empty")
        current = _utc(now or datetime.now(timezone.utc))
        news_state, news_reasons = _merge_news(news, symbol, current, self.policy)
        event_state, event_reasons = _event_state(events, symbol, current, self.policy)
        blocking = event_state == EventImportance.CRITICAL and self.policy.block_critical_events
        delay = event_state == EventImportance.HIGH and self.policy.delay_high_events
        reasons = tuple(news_reasons + event_reasons)
        return ContextAssessment(news_state, event_state, reasons, blocking, delay)
