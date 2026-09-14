from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.data.research_object_restore import restore_research_bundle
from app.data.research_object_store import AwsCliB2Repository, ResearchStoreError

_FINGERPRINT = "f" * 64
_PREFIX = f"gold/locked-research-datasets/v1/btc-usdt/{_FINGERPRINT}"


class MemoryB2(AwsCliB2Repository):
    def __init__(self, objects: dict[str, bytes]) -> None:
        super().__init__(
            endpoint="https://s3.eu-central-003.backblazeb2.com",
            bucket="test-bucket",
            region="eu-central-003",
        )
        self.objects = objects
        self.download_count = 0

    def download(self, key: str, destination: Path) -> None:
        self.download_count += 1
        if key not in self.objects:
            raise ResearchStoreError(f"missing object: {key}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[key])


def _manifest() -> dict[str, object]:
    return {
        "symbol": "BTC/USDT",
        "dataset_fingerprint": _FINGERPRINT,
        "object_prefix": _PREFIX,
        "qualification_status": "RESEARCH_PAPER_ONLY",
        "timeframes": {
            timeframe: {"parquet_file": f"parquet/{timeframe}.parquet"}
            for timeframe in ("15m", "1h", "4h", "1d")
        },
    }


def test_restore_rejects_invalid_fingerprint_before_remote_access(tmp_path: Path) -> None:
    repository = MemoryB2({})
    with pytest.raises(ResearchStoreError, match="64 lowercase hex"):
        restore_research_bundle(
            repository,
            symbol="BTC/USDT",
            dataset_fingerprint="NOT-A-FINGERPRINT",
            destination=tmp_path / "cache",
        )
    assert repository.download_count == 0


def test_restore_requires_manifest_commit_marker(tmp_path: Path) -> None:
    repository = MemoryB2({})
    with pytest.raises(ResearchStoreError, match="missing object"):
        restore_research_bundle(
            repository,
            symbol="BTC/USDT",
            dataset_fingerprint=_FINGERPRINT,
            destination=tmp_path / "cache",
        )
    assert not (tmp_path / "cache").exists()


def test_restore_rejects_manifest_redirect_before_partition_download(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["object_prefix"] = "gold/locked-research-datasets/v1/other/redirect"
    repository = MemoryB2(
        {
            f"{_PREFIX}/manifest.json": json.dumps(manifest).encode("utf-8"),
        }
    )
    with pytest.raises(ResearchStoreError, match="object prefix mismatch"):
        restore_research_bundle(
            repository,
            symbol="BTC/USDT",
            dataset_fingerprint=_FINGERPRINT,
            destination=tmp_path / "cache",
        )
    assert repository.download_count == 1
    assert not (tmp_path / "cache").exists()


def test_restore_rejects_unexpected_remote_parquet_path(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["timeframes"]["15m"]["parquet_file"] = "../../secret"  # type: ignore[index]
    repository = MemoryB2(
        {
            f"{_PREFIX}/manifest.json": json.dumps(manifest).encode("utf-8"),
        }
    )
    with pytest.raises(ResearchStoreError, match="parquet path invalid"):
        restore_research_bundle(
            repository,
            symbol="BTC/USDT",
            dataset_fingerprint=_FINGERPRINT,
            destination=tmp_path / "cache",
        )
    assert repository.download_count == 1
