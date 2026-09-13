from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from app.data.market_data import Candle
from app.data.providers.gateio import GateIOProvider
from app.data.providers.http import ProviderError
from app.data.quality import timeframe_seconds, validate_candles
from app.data.versioned_dataset import DatasetProvenance, build_versioned_dataset

_TIMEFRAMES = ("15m", "1h", "4h", "1d")
_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HistoricalBackfillPolicy:
    chunk_points: int = 900
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not 2 <= self.chunk_points <= 1000:
            raise ValueError("chunk_points must be in [2, 1000]")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")


@dataclass(frozen=True)
class LockedDatasetBundle:
    root: Path
    manifest: dict[str, object]
    candles_by_timeframe: dict[str, list[Candle]]


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _slug(symbol: str) -> str:
    return symbol.replace("/", "-").replace("_", "-").lower()


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


def _parse_row(value: object) -> Candle:
    if not isinstance(value, dict):
        raise ValueError("candle row must be an object")
    row = {str(key): item for key, item in value.items()}
    required = {
        "symbol", "timeframe", "timestamp", "open",
        "high", "low", "close", "volume",
    }
    if not required <= row.keys():
        raise ValueError("candle row is incomplete")
    stamp = datetime.fromisoformat(str(row["timestamp"]))
    if stamp.tzinfo is None:
        raise ValueError("candle timestamp must be timezone-aware")
    return Candle(
        symbol=str(row["symbol"]),
        timeframe=str(row["timeframe"]),
        timestamp=stamp.astimezone(timezone.utc),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row["volume"])),
    )


def _canonical(candles: list[Candle]) -> bytes:
    return json.dumps(
        [_row(item) for item in candles],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _hash_rows(candles: list[Candle]) -> str:
    return hashlib.sha256(_canonical(candles)).hexdigest()


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


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


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checkpoint_path(
    root: Path,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> Path:
    return (
        root / "checkpoints" / _slug(symbol) / timeframe
        / f"{int(start.timestamp())}-{int(end.timestamp())}.json"
    )


def _save_checkpoint(
    path: Path,
    *,
    provider: GateIOProvider,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    candles: list[Candle],
) -> tuple[list[Candle], dict[str, object]]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    rows_sha = _hash_rows(candles)
    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "provider": provider.name,
        "symbol": symbol,
        "timeframe": timeframe,
        "request_from": start.isoformat(),
        "request_to": end.isoformat(),
        "retrieved_at": retrieved_at,
        "rows_sha256": rows_sha,
        "rows": [_row(item) for item in candles],
    }
    _atomic_json(path, payload)
    return candles, {
        "file": str(path),
        "request_from": start.isoformat(),
        "request_to": end.isoformat(),
        "retrieved_at": retrieved_at,
        "rows_sha256": rows_sha,
        "candle_count": len(candles),
        "reused": False,
    }


def _load_checkpoint(
    path: Path,
    *,
    provider: GateIOProvider,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> tuple[list[Candle], dict[str, object]]:
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ValueError(f"invalid checkpoint: {path}")
    payload = {str(key): value for key, value in raw.items()}
    expected: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "provider": provider.name,
        "symbol": symbol,
        "timeframe": timeframe,
        "request_from": start.isoformat(),
        "request_to": end.isoformat(),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"checkpoint metadata mismatch: {path}: {key}")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"checkpoint rows missing: {path}")
    candles = [_parse_row(item) for item in rows]
    rows_sha = _hash_rows(candles)
    if payload.get("rows_sha256") != rows_sha:
        raise ValueError(f"checkpoint checksum mismatch: {path}")
    retrieved_at = payload.get("retrieved_at")
    if not isinstance(retrieved_at, str):
        raise ValueError(f"checkpoint retrieval timestamp missing: {path}")
    return candles, {
        "file": str(path),
        "request_from": start.isoformat(),
        "request_to": end.isoformat(),
        "retrieved_at": retrieved_at,
        "rows_sha256": rows_sha,
        "candle_count": len(candles),
        "reused": True,
    }


def _fetch(
    provider: GateIOProvider,
    *,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    policy: HistoricalBackfillPolicy,
    sleep_fn: Callable[[float], None],
) -> list[Candle]:
    for attempt in range(policy.max_retries + 1):
        try:
            return provider.get_candles_range(symbol, timeframe, start, end)
        except ProviderError:
            if attempt >= policy.max_retries:
                raise
            sleep_fn(policy.retry_backoff_seconds * (2**attempt))
    raise RuntimeError("unreachable retry state")


def _collect_timeframe(
    root: Path,
    *,
    provider: GateIOProvider,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    policy: HistoricalBackfillPolicy,
    sleep_fn: Callable[[float], None],
) -> tuple[list[Candle], list[dict[str, object]]]:
    step = timedelta(seconds=timeframe_seconds(timeframe))
    last_expected = end - step
    max_span = step * (policy.chunk_points - 1)
    cursor = start
    merged: dict[datetime, Candle] = {}
    checkpoints: list[dict[str, object]] = []

    while cursor < end:
        window_end = min(last_expected, cursor + max_span)
        path = _checkpoint_path(root, symbol, timeframe, cursor, window_end)
        if path.exists():
            rows, info = _load_checkpoint(
                path,
                provider=provider,
                symbol=symbol,
                timeframe=timeframe,
                start=cursor,
                end=window_end,
            )
        else:
            rows = _fetch(
                provider,
                symbol=symbol,
                timeframe=timeframe,
                start=cursor,
                end=window_end,
                policy=policy,
                sleep_fn=sleep_fn,
            )
            for candle in rows:
                timestamp = candle.timestamp.astimezone(timezone.utc)
                if (
                    candle.symbol != symbol
                    or candle.timeframe != timeframe
                    or timestamp < cursor
                    or timestamp > window_end
                ):
                    raise ValueError("provider returned candle outside request window")
            rows, info = _save_checkpoint(
                path,
                provider=provider,
                symbol=symbol,
                timeframe=timeframe,
                start=cursor,
                end=window_end,
                candles=rows,
            )
        info["file"] = path.relative_to(root).as_posix()
        checkpoints.append(info)

        for candle in rows:
            timestamp = candle.timestamp.astimezone(timezone.utc)
            previous = merged.get(timestamp)
            if previous is not None and previous != candle:
                raise ValueError(
                    f"conflicting historical candle at {timestamp.isoformat()}"
                )
            merged[timestamp] = candle

        if window_end >= last_expected:
            break
        cursor = window_end

    candles = [
        candle
        for timestamp, candle in sorted(merged.items())
        if start <= timestamp < end
    ]
    if not candles:
        raise ValueError(f"no historical {timeframe} candles")
    if candles[0].timestamp.astimezone(timezone.utc) != start:
        raise ValueError(f"{timeframe} start coverage mismatch")
    if candles[-1].timestamp.astimezone(timezone.utc) != last_expected:
        raise ValueError(f"{timeframe} end coverage mismatch")
    quality = validate_candles(candles, expected_timeframe=timeframe)
    if not quality.valid:
        raise ValueError(
            f"{timeframe} validation failed: " + "; ".join(quality.reasons)
        )
    return candles, checkpoints


def _write_locked(path: Path, candles: list[Candle]) -> str:
    content = "".join(
        json.dumps(
            _row(item),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ) + "\n"
        for item in candles
    )
    _atomic_text(path, content)
    return _file_sha(path)


def _source_uri(
    provider: GateIOProvider,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> str:
    pair = symbol.replace("/", "_").upper()
    last = end - timedelta(seconds=timeframe_seconds(timeframe))
    return (
        f"{provider.base_url.rstrip('/')}/spot/candlesticks"
        f"?currency_pair={pair}&interval={timeframe}"
        f"&from={int(start.timestamp())}&to={int(last.timestamp())}"
    )


def _guard_output(
    root: Path,
    *,
    provider: GateIOProvider,
    symbol: str,
    start: datetime,
    end: datetime,
    version: str,
) -> None:
    path = root / "manifest.json"
    if not path.exists():
        return
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ValueError("existing manifest is invalid")
    manifest = {str(key): value for key, value in raw.items()}
    expected: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "provider": provider.name,
        "symbol": symbol,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "dataset_version": version,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(
                f"output directory contains another dataset identity: {key}"
            )


def collect_historical_dataset(
    *,
    symbol: str,
    start: datetime,
    end: datetime,
    output_dir: str | Path,
    dataset_version: str,
    provider: GateIOProvider | None = None,
    policy: HistoricalBackfillPolicy | None = None,
    code_revision: str = "UNKNOWN",
    sleep_fn: Callable[[float], None] = time.sleep,
) -> LockedDatasetBundle:
    start_utc = _utc(start, "start")
    end_utc = _utc(end, "end")
    if start_utc >= end_utc:
        raise ValueError("start must be before end")
    for timeframe in _TIMEFRAMES:
        step = timeframe_seconds(timeframe)
        if int(start_utc.timestamp()) % step or int(end_utc.timestamp()) % step:
            raise ValueError(f"start/end must align to {timeframe}")

    gate = provider or GateIOProvider()
    applied = policy or HistoricalBackfillPolicy()
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    _guard_output(
        root,
        provider=gate,
        symbol=symbol,
        start=start_utc,
        end=end_utc,
        version=dataset_version,
    )

    candles_by_timeframe: dict[str, list[Candle]] = {}
    timeframe_entries: dict[str, object] = {}
    content_hashes: dict[str, str] = {}

    for timeframe in _TIMEFRAMES:
        candles, checkpoints = _collect_timeframe(
            root,
            provider=gate,
            symbol=symbol,
            timeframe=timeframe,
            start=start_utc,
            end=end_utc,
            policy=applied,
            sleep_fn=sleep_fn,
        )
        provenance = DatasetProvenance(
            provider=gate.name,
            provider_symbol=symbol.replace("/", "_").upper(),
            retrieved_at=datetime.now(timezone.utc),
            source_uri=_source_uri(gate, symbol, timeframe, start_utc, end_utc),
            license_id="gateio-public-api-v4",
        )
        dataset = build_versioned_dataset(
            dataset_id=(
                f"{_slug(symbol)}-{timeframe}-"
                f"{start_utc.date().isoformat()}-{end_utc.date().isoformat()}"
            ),
            version=dataset_version,
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            provenance=provenance,
            split_adjusted=False,
            created_at=datetime.now(timezone.utc),
        )
        locked_path = root / "locked" / _slug(symbol) / f"{timeframe}.jsonl"
        locked_sha = _write_locked(locked_path, candles)
        content_hashes[timeframe] = dataset.content_sha256
        candles_by_timeframe[timeframe] = candles
        timeframe_entries[timeframe] = {
            "dataset": dataset.to_manifest(),
            "locked_file": locked_path.relative_to(root).as_posix(),
            "locked_file_sha256": locked_sha,
            "checkpoint_chunks": checkpoints,
        }

    stable_identity: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "provider": gate.name,
        "symbol": symbol,
        "requested_start": start_utc.isoformat(),
        "requested_end": end_utc.isoformat(),
        "dataset_version": dataset_version,
        "content_sha256": content_hashes,
    }
    manifest: dict[str, object] = {
        **stable_identity,
        "code_revision": code_revision,
        "policy": {
            "chunk_points": applied.chunk_points,
            "max_retries": applied.max_retries,
            "retry_backoff_seconds": applied.retry_backoff_seconds,
        },
        "dataset_bundle_fingerprint": _fingerprint(stable_identity),
        "timeframes": timeframe_entries,
    }
    manifest["manifest_fingerprint"] = _fingerprint(manifest)
    _atomic_json(root / "manifest.json", manifest)
    return LockedDatasetBundle(root, manifest, candles_by_timeframe)


def _read_locked(path: Path) -> list[Candle]:
    candles: list[Candle] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw: object = json.loads(line)
                candles.append(_parse_row(raw))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid locked row {path}:{line_number}"
                ) from exc
    return candles


def load_locked_dataset(output_dir: str | Path) -> LockedDatasetBundle:
    root = Path(output_dir)
    raw = _read_json(root / "manifest.json")
    if not isinstance(raw, dict):
        raise ValueError("locked manifest must be an object")
    manifest = {str(key): value for key, value in raw.items()}

    stored_fingerprint = manifest.get("manifest_fingerprint")
    if not isinstance(stored_fingerprint, str):
        raise ValueError("manifest fingerprint missing")
    payload = dict(manifest)
    payload.pop("manifest_fingerprint", None)
    if _fingerprint(payload) != stored_fingerprint:
        raise ValueError("manifest fingerprint mismatch")

    symbol = manifest.get("symbol")
    start_raw = manifest.get("requested_start")
    end_raw = manifest.get("requested_end")
    version = manifest.get("dataset_version")
    provider = manifest.get("provider")
    content_hashes = manifest.get("content_sha256")
    entries = manifest.get("timeframes")
    if not isinstance(symbol, str):
        raise ValueError("manifest symbol missing")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise ValueError("manifest range missing")
    if not isinstance(version, str) or not isinstance(provider, str):
        raise ValueError("manifest identity missing")
    if not isinstance(content_hashes, dict) or not isinstance(entries, dict):
        raise ValueError("manifest timeframe metadata invalid")

    stable_identity: dict[str, object] = {
        "schema_version": manifest.get("schema_version"),
        "provider": provider,
        "symbol": symbol,
        "requested_start": start_raw,
        "requested_end": end_raw,
        "dataset_version": version,
        "content_sha256": content_hashes,
    }
    if manifest.get("dataset_bundle_fingerprint") != _fingerprint(stable_identity):
        raise ValueError("dataset bundle fingerprint mismatch")

    start = _utc(datetime.fromisoformat(start_raw), "requested_start")
    end = _utc(datetime.fromisoformat(end_raw), "requested_end")
    candles_by_timeframe: dict[str, list[Candle]] = {}

    for timeframe in _TIMEFRAMES:
        raw_entry = entries.get(timeframe)
        if not isinstance(raw_entry, dict):
            raise ValueError(f"missing timeframe manifest: {timeframe}")
        entry = {str(key): value for key, value in raw_entry.items()}
        locked_file = entry.get("locked_file")
        locked_sha = entry.get("locked_file_sha256")
        dataset_raw = entry.get("dataset")
        if (
            not isinstance(locked_file, str)
            or not isinstance(locked_sha, str)
            or not isinstance(dataset_raw, dict)
        ):
            raise ValueError(f"invalid timeframe manifest: {timeframe}")
        dataset = {str(key): value for key, value in dataset_raw.items()}
        path = root / locked_file
        if _file_sha(path) != locked_sha:
            raise ValueError(f"locked dataset file checksum mismatch: {timeframe}")
        candles = _read_locked(path)
        if not candles:
            raise ValueError(f"locked dataset empty: {timeframe}")
        if any(
            item.symbol != symbol or item.timeframe != timeframe
            for item in candles
        ):
            raise ValueError(f"locked dataset identity mismatch: {timeframe}")
        quality = validate_candles(candles, expected_timeframe=timeframe)
        if not quality.valid:
            raise ValueError(
                f"locked dataset validation failed for {timeframe}: "
                + "; ".join(quality.reasons)
            )
        expected_hash = content_hashes.get(timeframe)
        if not isinstance(expected_hash, str):
            raise ValueError(f"content hash missing: {timeframe}")
        if _hash_rows(candles) != expected_hash:
            raise ValueError(f"locked dataset content hash mismatch: {timeframe}")
        if dataset.get("content_sha256") != expected_hash:
            raise ValueError(f"dataset manifest hash mismatch: {timeframe}")
        if dataset.get("candle_count") != len(candles):
            raise ValueError(f"dataset manifest count mismatch: {timeframe}")
        expected_last = end - timedelta(seconds=timeframe_seconds(timeframe))
        if candles[0].timestamp.astimezone(timezone.utc) != start:
            raise ValueError(f"locked dataset start mismatch: {timeframe}")
        if candles[-1].timestamp.astimezone(timezone.utc) != expected_last:
            raise ValueError(f"locked dataset end mismatch: {timeframe}")
        candles_by_timeframe[timeframe] = candles

    return LockedDatasetBundle(root, manifest, candles_by_timeframe)
