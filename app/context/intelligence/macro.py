from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Iterable, Mapping

from app.context.models import EconomicEvent, EventImportance
from app.universe.instrument import Instrument

from .models import EventIntelligence, IntelligenceCategory


_COUNTRY_CURRENCY: Mapping[str, str] = {
    "US": "USD",
    "USA": "USD",
    "UNITED STATES": "USD",
    "EU": "EUR",
    "EUROZONE": "EUR",
    "UK": "GBP",
    "UNITED KINGDOM": "GBP",
    "JP": "JPY",
    "JAPAN": "JPY",
}


def _category(name: str) -> IntelligenceCategory:
    text = name.casefold()
    if any(token in text for token in ("rate", "inflation", "cpi", "gdp", "payroll", "jobs", "fomc")):
        return IntelligenceCategory.MACRO
    if any(token in text for token in ("regulation", "sec", "law", "policy")):
        return IntelligenceCategory.REGULATORY
    return IntelligenceCategory.OTHER


def _confidence(event: EconomicEvent, category: IntelligenceCategory) -> Decimal:
    base = {
        EventImportance.CRITICAL: Decimal("0.95"),
        EventImportance.HIGH: Decimal("0.85"),
        EventImportance.MEDIUM: Decimal("0.70"),
        EventImportance.LOW: Decimal("0.55"),
        EventImportance.NONE: Decimal("0.35"),
    }[event.importance]
    if category is IntelligenceCategory.OTHER:
        base -= Decimal("0.10")
    return max(Decimal("0"), base)


def enrich_macro_events(
    events: Iterable[EconomicEvent],
    instruments: Iterable[Instrument],
) -> tuple[EventIntelligence, ...]:
    universe = tuple(instruments)
    enriched: list[EventIntelligence] = []
    for event in events:
        symbols = event.symbols
        currency = (event.currency or _COUNTRY_CURRENCY.get(event.country.strip().upper(), "")).upper()
        if not symbols and currency:
            symbols = tuple(
                sorted(
                    instrument.symbol
                    for instrument in universe
                    if currency in {instrument.base_asset.upper(), instrument.quote_asset.upper()}
                )
            )
        normalized_event = replace(event, symbols=symbols, currency=currency or event.currency)
        category = _category(event.name)
        enriched.append(
            EventIntelligence(
                event=normalized_event,
                category=category,
                confidence=_confidence(normalized_event, category),
            )
        )
    return tuple(enriched)
