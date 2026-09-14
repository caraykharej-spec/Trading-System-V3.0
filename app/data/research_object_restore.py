from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from app.data.research_object_store import (
    AwsCliB2Repository,
    ResearchBundle,
    ResearchStoreError,
    verify_research_bundle,
)

_NAMESPACE = "gold/locked-research-datasets/v1"
_TIMEFRAMES = ("15m", "1h", "4h", "1d")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def _slug(symbol: str) -> str:
    value = symbol.replace("/", "-").replace("_", "-").lower()
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in value):
        raise ResearchStoreError("invalid research symbol")
    return value


def _expected_prefix(symbol: str, dataset_fingerprint: str) -> str:
    if not _FINGERPRINT_RE.fullmatch(dataset_fingerprint):
        raise ResearchStoreError("dataset fingerprint must be 64 lowercase hex characters")
    return f"{_NAMESPACE}/{_slug(symbol)}/{dataset_fingerprint}"


def _load_remote_manifest(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchStoreError("remote research manifest is missing or invalid") from exc
    if not isinstance(raw, dict):
        raise ResearchStoreError("remote research manifest must be an object")
    return {str(key): value for key, value in raw.items()}


def _validate_remote_identity(
    manifest: dict[str, object],
    *,
    symbol: str,
    dataset_fingerprint: str,
    expected_prefix: str,
) -> None:
    if manifest.get("symbol") != symbol:
        raise ResearchStoreError("remote research symbol mismatch")
    if manifest.get("dataset_fingerprint") != dataset_fingerprint:
        raise ResearchStoreError("remote research dataset fingerprint mismatch")
    if manifest.get("object_prefix") != expected_prefix:
        raise ResearchStoreError("remote research object prefix mismatch")
    if manifest.get("qualification_status") != "RESEARCH_PAPER_ONLY":
        raise ResearchStoreError("remote research qualification status mismatch")

    entries = manifest.get("timeframes")
    if not isinstance(entries, dict) or set(entries) != set(_TIMEFRAMES):
        raise ResearchStoreError("remote research timeframe map invalid")
    for timeframe in _TIMEFRAMES:
        entry = entries.get(timeframe)
        if not isinstance(entry, dict):
            raise ResearchStoreError(f"remote research timeframe missing: {timeframe}")
        if entry.get("parquet_file") != f"parquet/{timeframe}.parquet":
            raise ResearchStoreError(f"remote research parquet path invalid: {timeframe}")


def _cache_hit(
    destination: Path,
    *,
    symbol: str,
    dataset_fingerprint: str,
) -> ResearchBundle | None:
    if not destination.exists():
        return None
    if not destination.is_dir():
        raise ResearchStoreError("research cache destination exists but is not a directory")
    try:
        bundle = verify_research_bundle(destination)
    except ResearchStoreError as exc:
        raise ResearchStoreError("research cache exists but failed verification") from exc
    if bundle.dataset_fingerprint != dataset_fingerprint:
        raise ResearchStoreError("research cache fingerprint mismatch")
    if bundle.manifest.get("symbol") != symbol:
        raise ResearchStoreError("research cache symbol mismatch")
    return bundle


def restore_research_bundle(
    repository: AwsCliB2Repository,
    *,
    symbol: str,
    dataset_fingerprint: str,
    destination: str | Path,
) -> tuple[ResearchBundle, bool]:
    """Restore one committed GOLD research bundle from B2 and verify it fail-closed.

    Returns ``(bundle, cache_hit)``. A valid existing cache is reused without any remote
    request. Invalid or mismatched existing cache content is never overwritten silently.
    Remote paths are derived locally from the namespace, symbol, and fingerprint rather
    than trusted from downloaded metadata.
    """

    destination_path = Path(destination)
    cached = _cache_hit(
        destination_path,
        symbol=symbol,
        dataset_fingerprint=dataset_fingerprint,
    )
    if cached is not None:
        return cached, True

    prefix = _expected_prefix(symbol, dataset_fingerprint)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}.restore-",
            dir=destination_path.parent,
        )
    )
    try:
        manifest_path = temp_root / "manifest.json"
        repository.download(f"{prefix}/manifest.json", manifest_path)
        manifest = _load_remote_manifest(manifest_path)
        _validate_remote_identity(
            manifest,
            symbol=symbol,
            dataset_fingerprint=dataset_fingerprint,
            expected_prefix=prefix,
        )

        repository.download(f"{prefix}/checksums.json", temp_root / "checksums.json")
        for timeframe in _TIMEFRAMES:
            relative = f"parquet/{timeframe}.parquet"
            repository.download(f"{prefix}/{relative}", temp_root / relative)

        verified = verify_research_bundle(temp_root)
        if verified.dataset_fingerprint != dataset_fingerprint:
            raise ResearchStoreError("restored research fingerprint mismatch")
        if verified.object_prefix != prefix:
            raise ResearchStoreError("restored research object prefix mismatch")

        if destination_path.exists():
            raise ResearchStoreError("research cache destination appeared during restore")
        temp_root.replace(destination_path)
        return verify_research_bundle(destination_path), False
    except Exception:
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        raise
