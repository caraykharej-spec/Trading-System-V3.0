from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import NormalizedNewsRecord, RawNewsRecord


_WHITESPACE = re.compile(r"\s+")
_TRACKING_PREFIXES = ("utm_", "mc_", "ref")


def normalize_text(value: str) -> str:
    return _WHITESPACE.sub(" ", value.strip())


def normalize_title(value: str) -> str:
    compact = normalize_text(value).casefold()
    return re.sub(r"[^a-z0-9]+", " ", compact).strip()


def normalize_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    parts = urlsplit(value.strip())
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith(_TRACKING_PREFIXES)
    ]
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path, urlencode(query), ""))


def normalize_record(record: RawNewsRecord) -> NormalizedNewsRecord:
    title = normalize_text(record.title)
    return NormalizedNewsRecord(
        raw_ids=(record.raw_id,),
        title=title,
        normalized_title=normalize_title(title),
        published_at=record.published_at,
        sources=(normalize_text(record.source),),
        body=normalize_text(record.body),
        url=normalize_url(record.url),
        symbol_hints=tuple(sorted({hint.strip().upper() for hint in record.symbol_hints if hint.strip()})),
        country=record.country.strip().upper() if record.country and record.country.strip() else None,
    )
