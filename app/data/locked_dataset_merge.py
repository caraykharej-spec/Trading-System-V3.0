from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.data.historical_backfill import LockedDatasetBundle, load_locked_dataset
from app.data.market_data import Candle
from app.data.quality import timeframe_seconds, validate_candles
from app.data.versioned_dataset import DatasetProvenance, build_versioned_dataset

_TIMEFRAMES = ("15m", "1h", "4h", "1d")
_SCHEMA_VERSION = 1


def _slug(symbol: str) -> str:
    return symbol.replace("/", "-").replace("_", "-").lower()


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _row(candle: Candle) -> dict[str, str]:
    return {
        "symbol": candle.symbol,
        "timeframe": candle.timeframe,
        "timestamp": candle.timestamp.astimezone(timezone.utc).isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": str(candle.volume),
    }


def _hash_rows(candles: list[Candle]) -> str:
    payload = json.dumps(
        [_row(item) for item in candles],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _atomic_json(path: Path, payload: object) -> None:
    _atomic_text(
        path,
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
    )


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_locked(path: Path, candles: list[Candle]) -> str:
    content = "".join(
        json.dumps(
            _row(item),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
        for item in candles
    )
    _atomic_text(path, content)
    return _file_sha(path)


def _manifest_time(manifest: dict[str, object], key: str) -> datetime:
    raw = manifest.get(key)
    if not isinstance(raw, str):
        raise ValueError(f"shard manifest {key} missing")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ValueError(f"shard manifest {key} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _shard_summary(bundle: LockedDatasetBundle) -> dict[str, object]:
    manifest = bundle.manifest
    start = manifest.get("requested_start")
    end = manifest.get("requested_end")
    bundle_fingerprint = manifest.get("dataset_bundle_fingerprint")
    manifest_fingerprint = manifest.get("manifest_fingerprint")
    code_revision = manifest.get("code_revision", "UNKNOWN")
    content_hashes = manifest.get("content_sha256")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("shard range metadata missing")
    if not isinstance(bundle_fingerprint, str) or not isinstance(manifest_fingerprint, str):
        raise ValueError("shard fingerprints missing")
    if not isinstance(code_revision, str) or not isinstance(content_hashes, dict):
        raise ValueError("shard audit metadata invalid")
    return {
        "requested_start": start,
        "requested_end": end,
        "dataset_bundle_fingerprint": bundle_fingerprint,
        "manifest_fingerprint": manifest_fingerprint,
        "code_revision": code_revision,
        "content_sha256": {str(key): value for key, value in content_hashes.items()},
    }


def merge_locked_dataset_shards(
    shard_dirs: list[str | Path],
    *,
    output_dir: str | Path,
    dataset_version: str,
    code_revision: str = "UNKNOWN",
) -> LockedDatasetBundle:
    """Assemble contiguous verified locked shards into one new locked dataset.

    Every source shard is fully verified by ``load_locked_dataset`` before any
    candle is accepted. The merged annual bundle is then re-sealed and verified
    again through the same loader used by research backtests.
    """

    if len(shard_dirs) < 2:
        raise ValueError("at least two locked dataset shards are required")

    loaded = [load_locked_dataset(path) for path in shard_dirs]
    loaded.sort(key=lambda item: _manifest_time(item.manifest, "requested_start"))

    first_manifest = loaded[0].manifest
    symbol = first_manifest.get("symbol")
    provider = first_manifest.get("provider")
    if not isinstance(symbol, str) or not isinstance(provider, str):
        raise ValueError("shard identity metadata missing")

    starts = [_manifest_time(item.manifest, "requested_start") for item in loaded]
    ends = [_manifest_time(item.manifest, "requested_end") for item in loaded]
    for index, bundle in enumerate(loaded):
        if bundle.manifest.get("symbol") != symbol:
            raise ValueError("all shards must use the same symbol")
        if bundle.manifest.get("provider") != provider:
            raise ValueError("all shards must use the same provider")
        if index and starts[index] != ends[index - 1]:
            raise ValueError("locked dataset shards must be exactly contiguous")

    start = starts[0]
    end = ends[-1]
    summaries = [_shard_summary(item) for item in loaded]
    source_shards_fingerprint = _fingerprint(summaries)

    root = Path(output_dir)
    if (root / "manifest.json").exists():
        raise ValueError("output directory already contains a locked manifest")
    root.mkdir(parents=True, exist_ok=True)

    timeframe_entries: dict[str, object] = {}
    content_hashes: dict[str, str] = {}
    candles_by_timeframe: dict[str, list[Candle]] = {}

    for timeframe in _TIMEFRAMES:
        merged = [
            candle
            for bundle in loaded
            for candle in bundle.candles_by_timeframe[timeframe]
        ]
        if not merged:
            raise ValueError(f"merged {timeframe} dataset is empty")
        if len({candle.timestamp for candle in merged}) != len(merged):
            raise ValueError(f"duplicate candle timestamps across {timeframe} shards")
        quality = validate_candles(merged, expected_timeframe=timeframe)
        if not quality.valid:
            raise ValueError(
                f"merged {timeframe} validation failed: " + "; ".join(quality.reasons)
            )
        expected_last = end - timedelta(seconds=timeframe_seconds(timeframe))
        if merged[0].timestamp.astimezone(timezone.utc) != start:
            raise ValueError(f"merged {timeframe} start coverage mismatch")
        if merged[-1].timestamp.astimezone(timezone.utc) != expected_last:
            raise ValueError(f"merged {timeframe} end coverage mismatch")

        source_uri = f"urn:trading-system:locked-shards:{source_shards_fingerprint}"
        provenance = DatasetProvenance(
            provider=provider,
            provider_symbol=symbol.replace("/", "_").upper(),
            retrieved_at=datetime.now(timezone.utc),
            source_uri=source_uri,
            license_id="gateio-public-api-v4",
        )
        dataset = build_versioned_dataset(
            dataset_id=(
                f"{_slug(symbol)}-{timeframe}-"
                f"{start.date().isoformat()}-{end.date().isoformat()}-assembled"
            ),
            version=dataset_version,
            symbol=symbol,
            timeframe=timeframe,
            candles=merged,
            provenance=provenance,
            split_adjusted=False,
            created_at=datetime.now(timezone.utc),
        )
        if dataset.content_sha256 != _hash_rows(merged):
            raise RuntimeError("merged dataset canonical hash mismatch")

        locked_path = root / "locked" / _slug(symbol) / f"{timeframe}.jsonl"
        locked_sha = _write_locked(locked_path, merged)
        content_hashes[timeframe] = dataset.content_sha256
        candles_by_timeframe[timeframe] = merged
        timeframe_entries[timeframe] = {
            "dataset": dataset.to_manifest(),
            "locked_file": locked_path.relative_to(root).as_posix(),
            "locked_file_sha256": locked_sha,
            "checkpoint_chunks": [],
            "source_shards": [
                {
                    "requested_start": summary["requested_start"],
                    "requested_end": summary["requested_end"],
                    "dataset_bundle_fingerprint": summary[
                        "dataset_bundle_fingerprint"
                    ],
                    "manifest_fingerprint": summary["manifest_fingerprint"],
                    "content_sha256": summary["content_sha256"].get(timeframe)
                    if isinstance(summary["content_sha256"], dict)
                    else None,
                }
                for summary in summaries
            ],
            "source_shards_fingerprint": source_shards_fingerprint,
        }

    stable_identity: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "provider": provider,
        "symbol": symbol,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "dataset_version": dataset_version,
        "content_sha256": content_hashes,
    }
    manifest: dict[str, object] = {
        **stable_identity,
        "code_revision": code_revision,
        "policy": {
            "assembly": "VERIFIED_LOCKED_SHARDS",
            "network_refetch": False,
            "shard_count": len(loaded),
        },
        "dataset_bundle_fingerprint": _fingerprint(stable_identity),
        "timeframes": timeframe_entries,
        "source_shards": summaries,
        "source_shards_fingerprint": source_shards_fingerprint,
    }
    manifest["manifest_fingerprint"] = _fingerprint(manifest)
    _atomic_json(root / "manifest.json", manifest)

    verified = load_locked_dataset(root)
    return LockedDatasetBundle(root, verified.manifest, verified.candles_by_timeframe)
