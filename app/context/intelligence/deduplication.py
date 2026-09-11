from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from .models import NormalizedNewsRecord


def _tokens(record: NormalizedNewsRecord) -> set[str]:
    return {token for token in record.normalized_title.split() if token}


def _similarity(left: NormalizedNewsRecord, right: NormalizedNewsRecord) -> Decimal:
    a = _tokens(left)
    b = _tokens(right)
    if not a and not b:
        return Decimal("1")
    union = a | b
    if not union:
        return Decimal("0")
    return Decimal(len(a & b)) / Decimal(len(union))


def _merge(left: NormalizedNewsRecord, right: NormalizedNewsRecord) -> NormalizedNewsRecord:
    body = left.body if len(left.body) >= len(right.body) else right.body
    return replace(
        left,
        raw_ids=tuple(sorted(set(left.raw_ids) | set(right.raw_ids))),
        published_at=min(left.published_at, right.published_at),
        sources=tuple(sorted(set(left.sources) | set(right.sources))),
        body=body,
        url=left.url or right.url,
        symbol_hints=tuple(sorted(set(left.symbol_hints) | set(right.symbol_hints))),
        country=left.country or right.country,
    )


def deduplicate_news(
    records: list[NormalizedNewsRecord],
    *,
    similarity_threshold: Decimal = Decimal("0.80"),
    time_window: timedelta = timedelta(hours=8),
) -> tuple[NormalizedNewsRecord, ...]:
    if not Decimal("0") <= similarity_threshold <= Decimal("1"):
        raise ValueError("similarity_threshold must be in [0, 1]")
    if time_window.total_seconds() < 0:
        raise ValueError("time_window must be non-negative")

    result: list[NormalizedNewsRecord] = []
    for record in sorted(records, key=lambda item: item.published_at):
        merged = False
        for index, existing in enumerate(result):
            exact_url = bool(record.url and existing.url and record.url == existing.url)
            close_in_time = abs(record.published_at - existing.published_at) <= time_window
            near_title = close_in_time and _similarity(record, existing) >= similarity_threshold
            if exact_url or near_title:
                result[index] = _merge(existing, record)
                merged = True
                break
        if not merged:
            result.append(record)
    return tuple(sorted(result, key=lambda item: item.published_at, reverse=True))
