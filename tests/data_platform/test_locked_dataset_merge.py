from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.data.historical_backfill import HistoricalBackfillPolicy, collect_historical_dataset
from app.data.locked_dataset_merge import merge_locked_dataset_shards
from app.data.market_data import Candle
from app.data.providers.gateio import GateIOProvider
from app.data.quality import timeframe_seconds

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FakeGateProvider(GateIOProvider):
    calls: list[tuple[str, datetime, datetime]] = field(default_factory=list)

    def get_candles_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        self.calls.append((timeframe, start, end))
        step = timedelta(seconds=timeframe_seconds(timeframe))
        rows: list[Candle] = []
        cursor = start
        while cursor <= end:
            sequence = Decimal(str(int(cursor.timestamp())))
            base = Decimal("100") + (sequence % Decimal("1000")) / Decimal("1000")
            rows.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=cursor,
                    open=base,
                    high=base + Decimal("1"),
                    low=base - Decimal("1"),
                    close=base + Decimal("0.25"),
                    volume=Decimal("1000"),
                )
            )
            cursor += step
        return rows


def _collect(root, start: datetime, end: datetime):  # type: ignore[no-untyped-def]
    return collect_historical_dataset(
        symbol="BTC/USDT",
        start=start,
        end=end,
        output_dir=root,
        dataset_version="1.0.0",
        provider=FakeGateProvider(),
        policy=HistoricalBackfillPolicy(
            chunk_points=1000,
            max_retries=0,
            retry_backoff_seconds=0,
        ),
        code_revision="a" * 40,
        sleep_fn=lambda _: None,
    )


def test_merge_verified_contiguous_shards_into_new_locked_bundle(tmp_path):
    first_dir = tmp_path / "shard-a"
    second_dir = tmp_path / "shard-b"
    output = tmp_path / "annual"
    _collect(first_dir, START, START + timedelta(days=1))
    _collect(second_dir, START + timedelta(days=1), START + timedelta(days=2))

    merged = merge_locked_dataset_shards(
        [second_dir, first_dir],
        output_dir=output,
        dataset_version="2.0.0",
        code_revision="b" * 40,
    )

    assert merged.manifest["requested_start"] == START.isoformat()
    assert merged.manifest["requested_end"] == (START + timedelta(days=2)).isoformat()
    assert merged.manifest["dataset_version"] == "2.0.0"
    assert merged.manifest["policy"] == {
        "assembly": "VERIFIED_LOCKED_SHARDS",
        "network_refetch": False,
        "shard_count": 2,
    }
    assert len(str(merged.manifest["dataset_bundle_fingerprint"])) == 64
    assert len(str(merged.manifest["manifest_fingerprint"])) == 64
    assert len(str(merged.manifest["source_shards_fingerprint"])) == 64
    assert len(merged.candles_by_timeframe["15m"]) == 2 * 24 * 4
    assert len(merged.candles_by_timeframe["1h"]) == 2 * 24
    assert len(merged.candles_by_timeframe["4h"]) == 2 * 6
    assert len(merged.candles_by_timeframe["1d"]) == 2


def test_merge_rejects_gap_between_verified_shards(tmp_path):
    first_dir = tmp_path / "shard-a"
    second_dir = tmp_path / "shard-b"
    _collect(first_dir, START, START + timedelta(days=1))
    _collect(second_dir, START + timedelta(days=2), START + timedelta(days=3))

    with pytest.raises(ValueError, match="exactly contiguous"):
        merge_locked_dataset_shards(
            [first_dir, second_dir],
            output_dir=tmp_path / "annual",
            dataset_version="2.0.0",
        )


def test_merge_rejects_tampered_source_shard(tmp_path):
    first_dir = tmp_path / "shard-a"
    second_dir = tmp_path / "shard-b"
    _collect(first_dir, START, START + timedelta(days=1))
    _collect(second_dir, START + timedelta(days=1), START + timedelta(days=2))

    locked = second_dir / "locked" / "btc-usdt" / "15m.jsonl"
    locked.write_text(locked.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        merge_locked_dataset_shards(
            [first_dir, second_dir],
            output_dir=tmp_path / "annual",
            dataset_version="2.0.0",
        )
