from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from app.data.historical_backfill import LockedDatasetBundle, load_locked_dataset
from app.data.research_object_store import AwsCliB2Repository, ResearchStoreError

_NAMESPACE = "gold/locked-source-snapshots/v1"
_TIMEFRAMES = ("15m", "1h", "4h", "1d")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _slug(symbol: str) -> str:
    value = symbol.replace("/", "-").replace("_", "-").lower()
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in value):
        raise ResearchStoreError("invalid locked-source symbol")
    return value


def _prefix(symbol: str, dataset_fingerprint: str) -> str:
    if not _FINGERPRINT_RE.fullmatch(dataset_fingerprint):
        raise ResearchStoreError("locked-source fingerprint must be 64 lowercase hex characters")
    return f"{_NAMESPACE}/{_slug(symbol)}/{dataset_fingerprint}"


def _expected_locked_path(symbol: str, timeframe: str) -> str:
    return f"locked/{_slug(symbol)}/{timeframe}.jsonl"


def _safe_locked_path(root: Path, relative: str, *, symbol: str, timeframe: str) -> Path:
    expected = _expected_locked_path(symbol, timeframe)
    pure = PurePosixPath(relative)
    if relative != expected or pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise ResearchStoreError(f"unsafe locked-source path: {timeframe}")
    candidate = (root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ResearchStoreError("locked-source path escapes snapshot root") from exc
    return candidate


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchStoreError("locked-source manifest is missing or invalid") from exc
    if not isinstance(raw, dict):
        raise ResearchStoreError("locked-source manifest must be an object")
    return {str(key): value for key, value in raw.items()}


def _validate_manifest_identity(
    manifest: dict[str, object],
    *,
    expected_symbol: str | None = None,
    expected_fingerprint: str | None = None,
) -> tuple[str, str, dict[str, object]]:
    stored_manifest_fingerprint = manifest.get("manifest_fingerprint")
    if not isinstance(stored_manifest_fingerprint, str):
        raise ResearchStoreError("locked-source manifest fingerprint missing")
    payload = dict(manifest)
    payload.pop("manifest_fingerprint", None)
    if _canonical_fingerprint(payload) != stored_manifest_fingerprint:
        raise ResearchStoreError("locked-source manifest fingerprint mismatch")

    symbol = manifest.get("symbol")
    dataset_fingerprint = manifest.get("dataset_bundle_fingerprint")
    entries = manifest.get("timeframes")
    if not isinstance(symbol, str) or not isinstance(dataset_fingerprint, str):
        raise ResearchStoreError("locked-source identity metadata missing")
    if not isinstance(entries, dict) or set(entries) != set(_TIMEFRAMES):
        raise ResearchStoreError("locked-source timeframe map invalid")
    _prefix(symbol, dataset_fingerprint)
    if expected_symbol is not None and symbol != expected_symbol:
        raise ResearchStoreError("locked-source symbol mismatch")
    if expected_fingerprint is not None and dataset_fingerprint != expected_fingerprint:
        raise ResearchStoreError("locked-source dataset fingerprint mismatch")

    normalized_entries: dict[str, object] = {}
    for timeframe in _TIMEFRAMES:
        raw_entry = entries.get(timeframe)
        if not isinstance(raw_entry, dict):
            raise ResearchStoreError(f"locked-source timeframe missing: {timeframe}")
        entry = {str(key): value for key, value in raw_entry.items()}
        relative = entry.get("locked_file")
        expected_sha = entry.get("locked_file_sha256")
        if not isinstance(relative, str) or not isinstance(expected_sha, str):
            raise ResearchStoreError(f"locked-source file metadata invalid: {timeframe}")
        if relative != _expected_locked_path(symbol, timeframe):
            raise ResearchStoreError(f"locked-source file path invalid: {timeframe}")
        if not _FINGERPRINT_RE.fullmatch(expected_sha):
            raise ResearchStoreError(f"locked-source file hash invalid: {timeframe}")
        normalized_entries[timeframe] = entry
    return symbol, dataset_fingerprint, normalized_entries


def publish_locked_source_snapshot(
    source_dir: str | Path,
    repository: AwsCliB2Repository,
) -> LockedDatasetBundle:
    """Publish an already-sealed locked dataset byte-for-byte with manifest last."""

    bundle = load_locked_dataset(source_dir)
    manifest = bundle.manifest
    symbol, dataset_fingerprint, entries = _validate_manifest_identity(manifest)
    root = Path(source_dir)
    object_prefix = _prefix(symbol, dataset_fingerprint)

    for timeframe in _TIMEFRAMES:
        entry = entries[timeframe]
        assert isinstance(entry, dict)
        relative = str(entry["locked_file"])
        expected_sha = str(entry["locked_file_sha256"])
        local_path = _safe_locked_path(root, relative, symbol=symbol, timeframe=timeframe)
        if _file_sha256(local_path) != expected_sha:
            raise ResearchStoreError(f"locked-source local checksum mismatch: {timeframe}")
        repository.ensure_exact_object(local_path, f"{object_prefix}/{relative}", expected_sha)

    manifest_path = root / "manifest.json"
    repository.ensure_exact_object(
        manifest_path,
        f"{object_prefix}/manifest.json",
        _file_sha256(manifest_path),
    )
    return bundle


def _verified_cache(
    destination: Path,
    *,
    symbol: str,
    dataset_fingerprint: str,
) -> LockedDatasetBundle | None:
    if not destination.exists():
        return None
    if not destination.is_dir():
        raise ResearchStoreError("locked-source cache destination is not a directory")
    try:
        bundle = load_locked_dataset(destination)
    except (OSError, ValueError) as exc:
        raise ResearchStoreError("locked-source cache exists but failed verification") from exc
    if bundle.manifest.get("symbol") != symbol:
        raise ResearchStoreError("locked-source cache symbol mismatch")
    if bundle.manifest.get("dataset_bundle_fingerprint") != dataset_fingerprint:
        raise ResearchStoreError("locked-source cache fingerprint mismatch")
    return bundle


def restore_locked_source_snapshot(
    repository: AwsCliB2Repository,
    *,
    symbol: str,
    dataset_fingerprint: str,
    destination: str | Path,
) -> tuple[LockedDatasetBundle, bool]:
    """Restore an exact locked dataset snapshot and re-verify it with the canonical loader."""

    destination_path = Path(destination)
    cached = _verified_cache(
        destination_path,
        symbol=symbol,
        dataset_fingerprint=dataset_fingerprint,
    )
    if cached is not None:
        return cached, True

    object_prefix = _prefix(symbol, dataset_fingerprint)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}.locked-restore-",
            dir=destination_path.parent,
        )
    )
    try:
        manifest_path = temp_root / "manifest.json"
        repository.download(f"{object_prefix}/manifest.json", manifest_path)
        manifest = _read_manifest(manifest_path)
        remote_symbol, remote_fingerprint, entries = _validate_manifest_identity(
            manifest,
            expected_symbol=symbol,
            expected_fingerprint=dataset_fingerprint,
        )
        if _prefix(remote_symbol, remote_fingerprint) != object_prefix:
            raise ResearchStoreError("locked-source object prefix mismatch")

        for timeframe in _TIMEFRAMES:
            entry = entries[timeframe]
            assert isinstance(entry, dict)
            relative = str(entry["locked_file"])
            local_path = _safe_locked_path(
                temp_root,
                relative,
                symbol=symbol,
                timeframe=timeframe,
            )
            repository.download(f"{object_prefix}/{relative}", local_path)
            if _file_sha256(local_path) != str(entry["locked_file_sha256"]):
                raise ResearchStoreError(f"locked-source remote checksum mismatch: {timeframe}")

        verified = load_locked_dataset(temp_root)
        if verified.manifest.get("dataset_bundle_fingerprint") != dataset_fingerprint:
            raise ResearchStoreError("restored locked-source fingerprint mismatch")
        if destination_path.exists():
            raise ResearchStoreError("locked-source cache destination appeared during restore")
        temp_root.replace(destination_path)
        return load_locked_dataset(destination_path), False
    except Exception:
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        raise
