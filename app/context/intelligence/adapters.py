from __future__ import annotations

from app.context.models import NewsItem

from .models import RawNewsRecord


def records_from_news_items(items: list[NewsItem]) -> tuple[RawNewsRecord, ...]:
    """Bridge the existing provider contract into the V2 intelligence pipeline."""
    return tuple(
        RawNewsRecord(
            raw_id=item.item_id,
            title=item.title,
            published_at=item.published_at,
            source=item.source,
            symbol_hints=(item.symbol,) if item.symbol else (),
            country=item.country,
        )
        for item in items
    )
