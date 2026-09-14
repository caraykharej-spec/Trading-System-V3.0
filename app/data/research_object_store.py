from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.data.historical_backfill import LockedDatasetBundle, load_locked_dataset
from app.data.market_data import Candle

_SCHEMA_VERSION = 1
_STORAGE_FORMAT = "parquet"
_COMPRESSION = "zstd"
_RESEARCH_STATUS = "RESEARCH_PAPER_ONLY"
_IMMUTABILITY = "CONTENT_ADDRESSED_EXACT_RETRY"
_COMMIT_PROTOCOL = "DATA_THEN_CHECKSUMS_THEN_MANIFEST_LAST"
_NAMESPACE = "gold/locked-research-datasets/v1"
_TIMEFRAMES = ("15m", "1h", "4h", "1d")


class ResearchStoreError(RuntimeError):
    """Raised when a research-data-store operation cannot be completed safely."""


@dataclass(frozen=True)
class ResearchBundle:
    root: Path
    manifest: dict[str, object]
    dataset_fingerprint: str

    @property
    def object_prefix(self) -> str:
        value = self.manifest.get("object_prefix")
        if not isinstance(value, str):
            raise ResearchStoreError("research bundle object_prefix missing")
        return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _slug(symbol: str) -> str:
    return symbol.replace("/", "-").replace("_", "-").lower()


def _require_text(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ResearchStoreError(f"required manifest field missing: {key}")
    return value


def _load_pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise ResearchStoreError(
            "pyarrow is required for research Parquet storage; "
            "install the research-data optional dependency"
        ) from exc
    return pa, pq


def _writer_identity() -> dict[str, str]:
    pa, _ = _load_pyarrow()
    return {"library": "pyarrow", "version": str(pa.__version__)}


def _expected_relative_path(timeframe: str) -> str:
    if timeframe not in _TIMEFRAMES:
        raise ResearchStoreError(f"unsupported research timeframe: {timeframe}")
    return f"parquet/{timeframe}.parquet"


def _safe_partition_path(root: Path, relative: str, timeframe: str) -> Path:
    expected = _expected_relative_path(timeframe)
    pure = PurePosixPath(relative)
    if relative != expected or pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise ResearchStoreError(f"unsafe parquet path for {timeframe}: {relative}")
    root_resolved = root.resolve()
    candidate = (root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ResearchStoreError(f"parquet path escapes bundle root: {relative}") from exc
    return candidate


def _expected_object_prefix(symbol: str, dataset_fingerprint: str) -> str:
    return f"{_NAMESPACE}/{_slug(symbol)}/{dataset_fingerprint}"


def _validate_partition(candles: list[Candle], *, symbol: str, timeframe: str) -> None:
    if not candles:
        raise ResearchStoreError(f"cannot write empty partition: {timeframe}")
    previous = None
    for candle in candles:
        if candle.symbol != symbol or candle.timeframe != timeframe:
            raise ResearchStoreError(f"partition identity mismatch: {timeframe}")
        if candle.timestamp.tzinfo is None:
            raise ResearchStoreError(f"naive timestamp in partition: {timeframe}")
        if previous is not None and candle.timestamp <= previous:
            raise ResearchStoreError(f"timestamps are not strictly increasing: {timeframe}")
        if candle.high < max(candle.open, candle.close, candle.low):
            raise ResearchStoreError(f"invalid OHLC high: {timeframe}")
        if candle.low > min(candle.open, candle.close, candle.high):
            raise ResearchStoreError(f"invalid OHLC low: {timeframe}")
        if candle.volume < 0:
            raise ResearchStoreError(f"negative volume: {timeframe}")
        previous = candle.timestamp


def _write_parquet(path: Path, candles: list[Candle], *, symbol: str, timeframe: str) -> None:
    pa, pq = _load_pyarrow()
    _validate_partition(candles, symbol=symbol, timeframe=timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)
    decimal_type = pa.decimal128(38, 18)
    schema = pa.schema(
        [
            ("symbol", pa.string()),
            ("timeframe", pa.string()),
            ("timestamp", pa.timestamp("us", tz="UTC")),
            ("open", decimal_type),
            ("high", decimal_type),
            ("low", decimal_type),
            ("close", decimal_type),
            ("volume", decimal_type),
        ]
    )
    table = pa.Table.from_arrays(
        [
            pa.array([item.symbol for item in candles], type=pa.string()),
            pa.array([item.timeframe for item in candles], type=pa.string()),
            pa.array([item.timestamp for item in candles], type=pa.timestamp("us", tz="UTC")),
            pa.array([item.open for item in candles], type=decimal_type),
            pa.array([item.high for item in candles], type=decimal_type),
            pa.array([item.low for item in candles], type=decimal_type),
            pa.array([item.close for item in candles], type=decimal_type),
            pa.array([item.volume for item in candles], type=decimal_type),
        ],
        schema=schema,
    )
    pq.write_table(
        table,
        path,
        compression=_COMPRESSION,
        compression_level=9,
        use_dictionary=["symbol", "timeframe"],
        write_statistics=True,
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_research_bundle(
    locked_dataset_dir: str | Path,
    output_dir: str | Path,
    *,
    git_revision: str,
    tier: str = "gold",
) -> ResearchBundle:
    """Convert a verified locked dataset into immutable Parquet research objects."""

    if tier != "gold":
        raise ResearchStoreError("only gold locked-research datasets are publishable")
    if not git_revision:
        raise ResearchStoreError("git_revision is required")

    source: LockedDatasetBundle = load_locked_dataset(locked_dataset_dir)
    source_manifest = source.manifest
    symbol = _require_text(source_manifest, "symbol")
    source_bundle_fingerprint = _require_text(source_manifest, "dataset_bundle_fingerprint")
    source_manifest_fingerprint = _require_text(source_manifest, "manifest_fingerprint")
    requested_start = _require_text(source_manifest, "requested_start")
    requested_end = _require_text(source_manifest, "requested_end")
    dataset_version = _require_text(source_manifest, "dataset_version")
    provider = _require_text(source_manifest, "provider")
    content_hashes = source_manifest.get("content_sha256")
    if not isinstance(content_hashes, dict):
        raise ResearchStoreError("source content_sha256 map missing")

    root = Path(output_dir)
    timeframe_entries: dict[str, object] = {}
    for timeframe in _TIMEFRAMES:
        candles = source.candles_by_timeframe.get(timeframe)
        if not isinstance(candles, list):
            raise ResearchStoreError(f"source timeframe missing: {timeframe}")
        relative = _expected_relative_path(timeframe)
        parquet_path = _safe_partition_path(root, relative, timeframe)
        _write_parquet(parquet_path, candles, symbol=symbol, timeframe=timeframe)
        source_hash = content_hashes.get(timeframe)
        if not isinstance(source_hash, str):
            raise ResearchStoreError(f"source content hash missing: {timeframe}")
        timeframe_entries[timeframe] = {
            "row_count": len(candles),
            "source_content_sha256": source_hash,
            "parquet_file": relative,
            "parquet_sha256": _file_sha256(parquet_path),
        }

    stable_identity: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "tier": tier,
        "storage_format": _STORAGE_FORMAT,
        "compression": _COMPRESSION,
        "provider": provider,
        "symbol": symbol,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "dataset_version": dataset_version,
        "source_dataset_bundle_fingerprint": source_bundle_fingerprint,
        "source_manifest_fingerprint": source_manifest_fingerprint,
        "git_revision": git_revision,
        "writer": _writer_identity(),
        "timeframes": timeframe_entries,
    }
    dataset_fingerprint = _fingerprint(stable_identity)
    object_prefix = _expected_object_prefix(symbol, dataset_fingerprint)
    manifest: dict[str, object] = {
        **stable_identity,
        "dataset_fingerprint": dataset_fingerprint,
        "object_prefix": object_prefix,
        "qualification_status": _RESEARCH_STATUS,
        "immutability": _IMMUTABILITY,
        "commit_protocol": _COMMIT_PROTOCOL,
    }
    manifest["manifest_fingerprint"] = _fingerprint(manifest)

    checksum_payload = {
        str(entry["parquet_file"]): str(entry["parquet_sha256"])
        for entry in timeframe_entries.values()
        if isinstance(entry, dict)
    }
    _write_json(root / "checksums.json", checksum_payload)
    _write_json(root / "manifest.json", manifest)
    return ResearchBundle(root=root, manifest=manifest, dataset_fingerprint=dataset_fingerprint)


def verify_research_bundle(bundle_dir: str | Path) -> ResearchBundle:
    root = Path(bundle_dir)
    try:
        raw = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchStoreError("research manifest is missing or invalid") from exc
    if not isinstance(raw, dict):
        raise ResearchStoreError("research manifest must be an object")
    manifest = {str(key): value for key, value in raw.items()}

    stored_manifest_fp = _require_text(manifest, "manifest_fingerprint")
    fingerprint_payload = dict(manifest)
    fingerprint_payload.pop("manifest_fingerprint", None)
    if _fingerprint(fingerprint_payload) != stored_manifest_fp:
        raise ResearchStoreError("research manifest fingerprint mismatch")

    if manifest.get("schema_version") != _SCHEMA_VERSION:
        raise ResearchStoreError("unsupported research schema version")
    if manifest.get("tier") != "gold":
        raise ResearchStoreError("research tier must be gold")
    if manifest.get("storage_format") != _STORAGE_FORMAT:
        raise ResearchStoreError("research storage format mismatch")
    if manifest.get("compression") != _COMPRESSION:
        raise ResearchStoreError("research compression mismatch")
    if manifest.get("qualification_status") != _RESEARCH_STATUS:
        raise ResearchStoreError("research qualification status mismatch")
    if manifest.get("immutability") != _IMMUTABILITY:
        raise ResearchStoreError("research immutability policy mismatch")
    if manifest.get("commit_protocol") != _COMMIT_PROTOCOL:
        raise ResearchStoreError("research commit protocol mismatch")

    dataset_fingerprint = _require_text(manifest, "dataset_fingerprint")
    symbol = _require_text(manifest, "symbol")
    stable_identity = {
        key: manifest.get(key)
        for key in (
            "schema_version",
            "tier",
            "storage_format",
            "compression",
            "provider",
            "symbol",
            "requested_start",
            "requested_end",
            "dataset_version",
            "source_dataset_bundle_fingerprint",
            "source_manifest_fingerprint",
            "git_revision",
            "writer",
            "timeframes",
        )
    }
    if _fingerprint(stable_identity) != dataset_fingerprint:
        raise ResearchStoreError("research dataset fingerprint mismatch")
    expected_prefix = _expected_object_prefix(symbol, dataset_fingerprint)
    if manifest.get("object_prefix") != expected_prefix:
        raise ResearchStoreError("research object_prefix mismatch")

    entries = manifest.get("timeframes")
    if not isinstance(entries, dict) or set(entries) != set(_TIMEFRAMES):
        raise ResearchStoreError("research timeframe map invalid")

    expected_checksums: dict[str, str] = {}
    for timeframe in _TIMEFRAMES:
        raw_entry = entries.get(timeframe)
        if not isinstance(raw_entry, dict):
            raise ResearchStoreError(f"research timeframe missing: {timeframe}")
        entry = {str(key): value for key, value in raw_entry.items()}
        relative = _require_text(entry, "parquet_file")
        expected_sha = _require_text(entry, "parquet_sha256")
        path = _safe_partition_path(root, relative, timeframe)
        if not path.is_file():
            raise ResearchStoreError(f"research parquet missing: {timeframe}")
        if _file_sha256(path) != expected_sha:
            raise ResearchStoreError(f"research parquet checksum mismatch: {timeframe}")
        expected_checksums[relative] = expected_sha

    try:
        checksums_raw = json.loads((root / "checksums.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchStoreError("checksums.json is missing or invalid") from exc
    if not isinstance(checksums_raw, dict):
        raise ResearchStoreError("checksums.json must be an object")
    checksums = {str(key): value for key, value in checksums_raw.items()}
    if set(checksums) != set(expected_checksums):
        raise ResearchStoreError("checksums.json partition set mismatch")
    for relative, expected_sha in expected_checksums.items():
        if checksums.get(relative) != expected_sha:
            raise ResearchStoreError(f"checksums.json mismatch: {relative}")

    return ResearchBundle(root=root, manifest=manifest, dataset_fingerprint=dataset_fingerprint)


class AwsCliB2Repository:
    """Fail-closed Backblaze B2 repository using the S3-compatible AWS CLI."""

    def __init__(self, *, endpoint: str, bucket: str, region: str) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("B2 endpoint must use https")
        if not bucket:
            raise ValueError("B2 bucket is required")
        if not region:
            raise ValueError("B2 signing region is required")
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.region = region

    @classmethod
    def from_environment(cls) -> AwsCliB2Repository:
        endpoint = os.environ.get("B2_S3_ENDPOINT", "")
        bucket = os.environ.get("B2_BUCKET_NAME", "")
        region = os.environ.get("B2_S3_REGION") or os.environ.get("AWS_DEFAULT_REGION", "")
        return cls(endpoint=endpoint, bucket=bucket, region=region)

    def _command(self, *args: str) -> list[str]:
        return [
            "aws",
            "s3api",
            *args,
            "--endpoint-url",
            self.endpoint,
            "--region",
            self.region,
        ]

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                self._command(*args),
                check=True,
                text=True,
                capture_output=True,
            )
        except FileNotFoundError as exc:
            raise ResearchStoreError("AWS CLI is not installed") from exc
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or exc.stdout or "AWS CLI operation failed").strip()
            raise ResearchStoreError(message) from exc

    def object_exists(self, key: str) -> bool:
        try:
            subprocess.run(
                self._command("head-object", "--bucket", self.bucket, "--key", key),
                check=True,
                text=True,
                capture_output=True,
            )
            return True
        except FileNotFoundError as exc:
            raise ResearchStoreError("AWS CLI is not installed") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").lower()
            if "not found" in stderr or "404" in stderr or "nosuchkey" in stderr:
                return False
            raise ResearchStoreError((exc.stderr or exc.stdout or "head-object failed").strip()) from exc

    def download(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            "get-object",
            "--bucket",
            self.bucket,
            "--key",
            key,
            str(destination),
        )

    def ensure_exact_object(self, local_path: Path, key: str, expected_sha: str) -> None:
        """Create or idempotently reuse an object only when bytes are exactly identical.

        Backblaze's documented S3 Put Object headers do not advertise conditional create.
        The content-addressed namespace therefore binds all lineage into the fingerprint.
        Concurrent writers for one prefix can only have the same expected bytes; a mismatch
        is always rejected. Bucket versioning additionally preserves prior object versions.
        """

        if self.object_exists(key):
            self._verify_remote_sha(key, expected_sha)
            return
        self._run(
            "put-object",
            "--bucket",
            self.bucket,
            "--key",
            key,
            "--body",
            str(local_path),
        )
        self._verify_remote_sha(key, expected_sha)

    def _verify_remote_sha(self, key: str, expected_sha: str) -> None:
        with tempfile.TemporaryDirectory(prefix="b2-exact-") as temp_dir:
            readback = Path(temp_dir) / "object"
            self.download(key, readback)
            actual_sha = _file_sha256(readback)
            if actual_sha != expected_sha:
                raise ResearchStoreError(f"B2 object checksum mismatch: {key}")


def publish_research_bundle(bundle_dir: str | Path, repository: AwsCliB2Repository) -> ResearchBundle:
    """Publish a verified bundle and use manifest.json as the final commit marker."""

    bundle = verify_research_bundle(bundle_dir)
    entries = bundle.manifest.get("timeframes")
    if not isinstance(entries, dict):
        raise ResearchStoreError("research timeframe map missing")

    upload_plan: list[tuple[Path, str, str]] = []
    for timeframe in _TIMEFRAMES:
        raw_entry = entries.get(timeframe)
        if not isinstance(raw_entry, dict):
            raise ResearchStoreError(f"research timeframe missing: {timeframe}")
        entry = {str(key): value for key, value in raw_entry.items()}
        relative = _require_text(entry, "parquet_file")
        expected_sha = _require_text(entry, "parquet_sha256")
        local_path = _safe_partition_path(bundle.root, relative, timeframe)
        upload_plan.append((local_path, f"{bundle.object_prefix}/{relative}", expected_sha))

    checksums = bundle.root / "checksums.json"
    manifest = bundle.root / "manifest.json"
    upload_plan.append(
        (checksums, f"{bundle.object_prefix}/checksums.json", _file_sha256(checksums))
    )

    for local_path, key, expected_sha in upload_plan:
        repository.ensure_exact_object(local_path, key, expected_sha)

    manifest_key = f"{bundle.object_prefix}/manifest.json"
    repository.ensure_exact_object(manifest, manifest_key, _file_sha256(manifest))
    return bundle
