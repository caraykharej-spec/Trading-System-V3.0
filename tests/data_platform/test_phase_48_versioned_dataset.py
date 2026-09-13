from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.data.market_data import Candle
from app.data.versioned_dataset import (
    DatasetProvenance,
    SplitEvent,
    build_versioned_dataset,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def candles(count: int = 3):
    return tuple(
        Candle(
            "AMD/USDT",
            "1h",
            NOW + timedelta(hours=index),
            Decimal("100"),
            Decimal("102"),
            Decimal("99"),
            Decimal("101"),
            Decimal("1000"),
        )
        for index in range(count)
    )


def provenance():
    return DatasetProvenance(
        "yahoo",
        "AMD",
        NOW,
        "https://query.example/AMD",
        "provider-terms-v1",
    )


def test_manifest_is_reproducible_and_records_provenance():
    first = build_versioned_dataset(
        dataset_id="amd-1h",
        version="1.0.0",
        symbol="AMD/USDT",
        timeframe="1h",
        candles=candles(),
        provenance=provenance(),
        split_adjusted=True,
        created_at=NOW,
    )
    second = build_versioned_dataset(
        dataset_id="amd-1h",
        version="1.0.1",
        symbol="AMD/USDT",
        timeframe="1h",
        candles=candles(),
        provenance=provenance(),
        split_adjusted=True,
        created_at=NOW,
    )

    assert first.content_sha256 == second.content_sha256
    assert len(first.content_sha256) == 64
    assert first.to_manifest()["provenance"]["provider"] == "yahoo"


def test_duplicate_and_gap_fail_closed():
    rows = candles()
    with pytest.raises(ValueError, match="duplicate"):
        build_versioned_dataset(
            dataset_id="bad",
            version="1.0.0",
            symbol="AMD/USDT",
            timeframe="1h",
            candles=(rows[0], rows[0]),
            provenance=provenance(),
            split_adjusted=True,
        )
    with pytest.raises(ValueError, match="gap"):
        build_versioned_dataset(
            dataset_id="bad",
            version="1.0.0",
            symbol="AMD/USDT",
            timeframe="1h",
            candles=(rows[0], rows[2]),
            provenance=provenance(),
            split_adjusted=True,
        )


def test_unadjusted_split_dataset_fails_closed():
    with pytest.raises(ValueError, match="split adjustment"):
        build_versioned_dataset(
            dataset_id="amd-1h",
            version="1.0.0",
            symbol="AMD/USDT",
            timeframe="1h",
            candles=candles(),
            provenance=provenance(),
            split_adjusted=False,
            split_events=(SplitEvent(NOW, Decimal("2"), Decimal("1"), "issuer"),),
        )
