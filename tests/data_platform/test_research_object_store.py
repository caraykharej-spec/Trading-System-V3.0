from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.data.historical_backfill import HistoricalBackfillPolicy, collect_historical_dataset
from app.data.market_data import Candle
from app.data.providers.gateio import GateIOProvider
from app.data.quality import timeframe_seconds
from app.data.research_object_store import (
    AwsCliB2Repository,
    ResearchStoreError,
    _fingerprint,
    _safe_partition_path,
    build_research_bundle,
    verify_research_bundle,
)

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
            base = Decimal("100") + Decimal(str(int(cursor.timestamp()) % 1000)) / Decimal("1000")
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


def _locked_dataset(tmp_path):  # type: ignore[no-untyped-def]
    root = tmp_path / "locked-source"
    return collect_historical_dataset(
        symbol="BTC/USDT",
        start=_START,
        end=_END,
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


def test_build_and_verify_parquet_research_bundle(tmp_path):
    source = _locked_dataset(tmp_path)
    output = tmp_path / "research-bundle"

    built = build_research_bundle(source.root, output, git_revision="b" * 40)
    verified = verify_research_bundle(output)

    assert built.dataset_fingerprint == verified.dataset_fingerprint
    assert verified.manifest["storage_format"] == "parquet"
    assert verified.manifest["compression"] == "zstd"
    assert verified.manifest["qualification_status"] == "RESEARCH_PAPER_ONLY"
    assert verified.object_prefix.startswith("gold/locked-research-datasets/v1/btc-usdt/")
    assert (output / "manifest.json").is_file()
    assert (output / "checksums.json").is_file()
    for timeframe in ("15m", "1h", "4h", "1d"):
        assert (output / "parquet" / f"{timeframe}.parquet").is_file()


def test_git_revision_is_bound_into_dataset_fingerprint(tmp_path):
    source = _locked_dataset(tmp_path)
    first = build_research_bundle(source.root, tmp_path / "first", git_revision="1" * 40)
    second = build_research_bundle(source.root, tmp_path / "second", git_revision="2" * 40)
    assert first.dataset_fingerprint != second.dataset_fingerprint
    assert first.object_prefix != second.object_prefix


def test_research_bundle_detects_parquet_tampering(tmp_path):
    source = _locked_dataset(tmp_path)
    output = tmp_path / "research-bundle"
    build_research_bundle(source.root, output, git_revision="c" * 40)

    parquet = output / "parquet" / "15m.parquet"
    parquet.write_bytes(parquet.read_bytes() + b"tamper")

    with pytest.raises(ResearchStoreError, match="checksum mismatch"):
        verify_research_bundle(output)


def test_research_bundle_detects_checksum_manifest_tampering(tmp_path):
    source = _locked_dataset(tmp_path)
    output = tmp_path / "research-bundle"
    build_research_bundle(source.root, output, git_revision="d" * 40)

    checksums_path = output / "checksums.json"
    checksums = json.loads(checksums_path.read_text(encoding="utf-8"))
    checksums["parquet/15m.parquet"] = "0" * 64
    checksums_path.write_text(json.dumps(checksums), encoding="utf-8")

    with pytest.raises(ResearchStoreError, match="checksums.json mismatch"):
        verify_research_bundle(output)


def test_research_bundle_detects_manifest_tampering(tmp_path):
    source = _locked_dataset(tmp_path)
    output = tmp_path / "research-bundle"
    build_research_bundle(source.root, output, git_revision="e" * 40)

    manifest = output / "manifest.json"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace("RESEARCH_PAPER_ONLY", "QUALIFIED"), encoding="utf-8")

    with pytest.raises(ResearchStoreError, match="manifest fingerprint mismatch"):
        verify_research_bundle(output)


def test_object_prefix_is_recomputed_not_trusted(tmp_path):
    source = _locked_dataset(tmp_path)
    output = tmp_path / "research-bundle"
    build_research_bundle(source.root, output, git_revision="f" * 40)

    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["object_prefix"] = "gold/locked-research-datasets/v1/other/redirect"
    payload = dict(manifest)
    payload.pop("manifest_fingerprint")
    manifest["manifest_fingerprint"] = _fingerprint(payload)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ResearchStoreError, match="object_prefix mismatch"):
        verify_research_bundle(output)


def test_partition_path_cannot_escape_bundle(tmp_path):
    with pytest.raises(ResearchStoreError, match="unsafe parquet path"):
        _safe_partition_path(tmp_path, "../../secret", "15m")
    with pytest.raises(ResearchStoreError, match="unsafe parquet path"):
        _safe_partition_path(tmp_path, "/tmp/secret", "15m")


class MemoryB2(AwsCliB2Repository):
    def __init__(self) -> None:
        super().__init__(
            endpoint="https://s3.eu-central-003.backblazeb2.com",
            bucket="test-bucket",
            region="eu-central-003",
        )
        self.objects: dict[str, bytes] = {}

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def download(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[key])

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        values = list(args)
        assert values[0] == "put-object"
        key = values[values.index("--key") + 1]
        body = Path(values[values.index("--body") + 1])
        self.objects[key] = body.read_bytes()
        return subprocess.CompletedProcess(["aws"], 0, "", "")


def test_existing_exact_object_is_idempotently_reused(tmp_path):
    local = tmp_path / "object"
    local.write_bytes(b"same-content")
    expected_sha = __import__("hashlib").sha256(local.read_bytes()).hexdigest()
    repository = MemoryB2()
    repository.objects["key"] = local.read_bytes()

    repository.ensure_exact_object(local, "key", expected_sha)
    assert repository.objects["key"] == b"same-content"


def test_existing_mismatched_object_is_rejected(tmp_path):
    local = tmp_path / "object"
    local.write_bytes(b"expected")
    expected_sha = __import__("hashlib").sha256(local.read_bytes()).hexdigest()
    repository = MemoryB2()
    repository.objects["key"] = b"different"

    with pytest.raises(ResearchStoreError, match="B2 object checksum mismatch"):
        repository.ensure_exact_object(local, "key", expected_sha)


def test_aws_cli_command_always_has_signing_region():
    repository = AwsCliB2Repository(
        endpoint="https://s3.eu-central-003.backblazeb2.com",
        bucket="test-bucket",
        region="eu-central-003",
    )
    command = repository._command("head-object", "--bucket", "test-bucket", "--key", "x")
    assert command[-2:] == ["--region", "eu-central-003"]
