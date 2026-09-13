from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from app.data.market_data import Candle
from app.data.quality import validate_candles

_VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")


@dataclass(frozen=True)
class DatasetProvenance:
    provider: str
    provider_symbol: str
    retrieved_at: datetime
    source_uri: str
    license_id: str

    def __post_init__(self) -> None:
        if not all(
            (self.provider, self.provider_symbol, self.source_uri, self.license_id)
        ):
            raise ValueError("dataset provenance fields must be non-empty")
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")


@dataclass(frozen=True)
class SplitEvent:
    effective_at: datetime
    numerator: Decimal
    denominator: Decimal
    source: str

    def __post_init__(self) -> None:
        if self.effective_at.tzinfo is None:
            raise ValueError("split timestamp must be timezone-aware")
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValueError("split ratio must be positive")
        if not self.source:
            raise ValueError("split source must be non-empty")


@dataclass(frozen=True)
class VersionedCandleDataset:
    dataset_id: str
    version: str
    symbol: str
    timeframe: str
    created_at: datetime
    provenance: DatasetProvenance
    candle_count: int
    first_timestamp: datetime
    last_timestamp: datetime
    split_adjusted: bool
    split_events: tuple[SplitEvent, ...]
    content_sha256: str

    def to_manifest(self) -> dict[str, object]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["first_timestamp"] = self.first_timestamp.isoformat()
        payload["last_timestamp"] = self.last_timestamp.isoformat()
        provenance = dict(payload["provenance"])  # type: ignore[arg-type]
        provenance["retrieved_at"] = self.provenance.retrieved_at.isoformat()
        payload["provenance"] = provenance
        payload["split_events"] = [
            {
                "effective_at": item.effective_at.isoformat(),
                "numerator": str(item.numerator),
                "denominator": str(item.denominator),
                "source": item.source,
            }
            for item in self.split_events
        ]
        return payload


def _canonical_rows(candles: tuple[Candle, ...]) -> bytes:
    rows = [
        {
            "symbol": item.symbol,
            "timeframe": item.timeframe,
            "timestamp": item.timestamp.astimezone(timezone.utc).isoformat(),
            "open": str(item.open),
            "high": str(item.high),
            "low": str(item.low),
            "close": str(item.close),
            "volume": str(item.volume),
        }
        for item in candles
    ]
    return json.dumps(
        rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def build_versioned_dataset(
    *,
    dataset_id: str,
    version: str,
    symbol: str,
    timeframe: str,
    candles: Iterable[Candle],
    provenance: DatasetProvenance,
    split_adjusted: bool,
    split_events: Iterable[SplitEvent] = (),
    allow_session_gaps: bool = False,
    created_at: datetime | None = None,
) -> VersionedCandleDataset:
    if not dataset_id:
        raise ValueError("dataset_id must be non-empty")
    if not _VERSION.fullmatch(version):
        raise ValueError("version must use numeric semantic versioning")
    items = tuple(candles)
    if not items:
        raise ValueError("dataset cannot be empty")
    if any(item.symbol != symbol or item.timeframe != timeframe for item in items):
        raise ValueError("dataset candles must match symbol and timeframe")
    timestamps = [item.timestamp for item in items]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError("duplicate candle timestamp")
    quality = validate_candles(
        items,
        expected_timeframe=timeframe,
        allow_session_gaps=allow_session_gaps,
    )
    if not quality.valid:
        raise ValueError("invalid historical dataset: " + "; ".join(quality.reasons))
    events = tuple(sorted(split_events, key=lambda item: item.effective_at))
    if events and not split_adjusted:
        raise ValueError("datasets with split events must declare split adjustment")
    generated_at = created_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    return VersionedCandleDataset(
        dataset_id=dataset_id,
        version=version,
        symbol=symbol,
        timeframe=timeframe,
        created_at=generated_at.astimezone(timezone.utc),
        provenance=provenance,
        candle_count=len(items),
        first_timestamp=items[0].timestamp,
        last_timestamp=items[-1].timestamp,
        split_adjusted=split_adjusted,
        split_events=events,
        content_sha256=hashlib.sha256(_canonical_rows(items)).hexdigest(),
    )
