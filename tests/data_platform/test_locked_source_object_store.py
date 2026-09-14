from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.data.historical_backfill import (
    HistoricalBackfillPolicy,
    collect_historical_dataset,
    load_locked_dataset,
)
from app.data.locked_source_object_store import (
    publish_locked_source_snapshot,
    restore_locked_source_snapshot,
)
from app.data.market_data import Candle
from app.data.providers.gateio import GateIOProvider
from app.data.quality import timeframe_seconds
from app.data.research_object_store import AwsCliB2Repository, ResearchStoreError

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_END = datetime(2026, 1, 3, tzinfo=timezone.utc)


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
            rows.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=cursor,
                    open=Decimal("100"),
                    high=Decimal("101"),
                    low=Decimal("99"),
                    close=Decimal("100.25"),
                    volume=Decimal("1000"),
                )
            )
            cursor += step
        return rows


def _source(tmp_path: Path):  # type: ignore[no-untyped-def]
    return collect_historical_dataset(
        symbol="BTC/USDT",
        start=_START,
        end=_END,
        output_dir=tmp_path / "source",
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


class MemoryB2(AwsCliB2Repository):
    def __init__(self) -> None:
        super().__init__(
            endpoint="https://s3.eu-central-003.backblazeb2.com",
            bucket="test-bucket",
            region="eu-central-003",
        )
        self.objects: dict[str, bytes] = {}
        self.download_count = 0

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def download(self, key: str, destination: Path) -> None:
        self.download_count += 1
        if key not in self.objects:
            raise ResearchStoreError(f"missing object: {key}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[key])

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        values = list(args)
        assert values[0] == "put-object"
        key = values[values.index("--key") + 1]
        body = Path(values[values.index("--body") + 1])
        self.objects[key] = body.read_bytes()
        return subprocess.CompletedProcess(["aws"], 0, "", "")


def test_locked_source_round_trip_preserves_exact_fingerprints(tmp_path: Path) -> None:
    source = _source(tmp_path)
    repository = MemoryB2()
    published = publish_locked_source_snapshot(source.root, repository)

    restored, cache_hit = restore_locked_source_snapshot(
        repository,
        symbol="BTC/USDT",
        dataset_fingerprint=str(source.manifest["dataset_bundle_fingerprint"]),
        destination=tmp_path / "restored",
    )

    assert cache_hit is False
    assert restored.manifest["dataset_bundle_fingerprint"] == published.manifest[
        "dataset_bundle_fingerprint"
    ]
    assert restored.manifest["manifest_fingerprint"] == published.manifest[
        "manifest_fingerprint"
    ]
    assert (tmp_path / "restored" / "manifest.json").read_bytes() == (
        source.root / "manifest.json"
    ).read_bytes()


def test_valid_restored_cache_is_reused_without_remote_access(tmp_path: Path) -> None:
    source = _source(tmp_path)
    repository = MemoryB2()
    publish_locked_source_snapshot(source.root, repository)
    destination = tmp_path / "restored"
    restore_locked_source_snapshot(
        repository,
        symbol="BTC/USDT",
        dataset_fingerprint=str(source.manifest["dataset_bundle_fingerprint"]),
        destination=destination,
    )
    before = repository.download_count
    restored, cache_hit = restore_locked_source_snapshot(
        repository,
        symbol="BTC/USDT",
        dataset_fingerprint=str(source.manifest["dataset_bundle_fingerprint"]),
        destination=destination,
    )
    assert cache_hit is True
    assert repository.download_count == before
    assert load_locked_dataset(destination).manifest == restored.manifest


def test_corrupt_existing_cache_fails_closed_without_overwrite(tmp_path: Path) -> None:
    source = _source(tmp_path)
    repository = MemoryB2()
    publish_locked_source_snapshot(source.root, repository)
    destination = tmp_path / "restored"
    restore_locked_source_snapshot(
        repository,
        symbol="BTC/USDT",
        dataset_fingerprint=str(source.manifest["dataset_bundle_fingerprint"]),
        destination=destination,
    )
    manifest = destination / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    before = repository.download_count
    with pytest.raises(ResearchStoreError, match="cache exists but failed verification"):
        restore_locked_source_snapshot(
            repository,
            symbol="BTC/USDT",
            dataset_fingerprint=str(source.manifest["dataset_bundle_fingerprint"]),
            destination=destination,
        )
    assert repository.download_count == before


def test_missing_manifest_commit_marker_fails_closed(tmp_path: Path) -> None:
    repository = MemoryB2()
    with pytest.raises(ResearchStoreError, match="missing object"):
        restore_locked_source_snapshot(
            repository,
            symbol="BTC/USDT",
            dataset_fingerprint="f" * 64,
            destination=tmp_path / "restored",
        )
    assert not (tmp_path / "restored").exists()
