from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from app.data.historical_backfill import LockedDatasetBundle, load_locked_dataset
from app.data.market_data import Candle
from app.data.providers.http import ProviderError
from app.data.quality import timeframe_seconds, validate_candles
from app.data.versioned_dataset import DatasetProvenance, build_versioned_dataset

_BASE_URL = "https://download.gatedata.org"
_TIMEFRAMES = ("15m", "1h", "4h", "1d")
_BASE_SECONDS = 300
_SCHEMA_VERSION = 1

ArchiveDownloader = Callable[[str, Path], None]


@dataclass(frozen=True)
class GateDealsArchivePolicy:
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0
    timeout_seconds: int = 120

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass
class _FiveMinuteBucket:
    timestamp: datetime
    open_key: tuple[Decimal, int] | None = None
    close_key: tuple[Decimal, int] | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    quote_volume: Decimal = Decimal("0")
    trade_count: int = 0

    def push(
        self,
        *,
        event_key: tuple[Decimal, int],
        price: Decimal,
        base_amount: Decimal,
    ) -> None:
        if self.open_key is None or event_key < self.open_key:
            self.open_key = event_key
            self.open = price
        if self.close_key is None or event_key > self.close_key:
            self.close_key = event_key
            self.close = price
        self.high = price if self.high is None else max(self.high, price)
        self.low = price if self.low is None else min(self.low, price)
        self.quote_volume += price * base_amount
        self.trade_count += 1

    def candle(self, symbol: str) -> Candle:
        if self.open is None or self.high is None or self.low is None or self.close is None:
            raise ValueError(f"incomplete 5m trade bucket at {self.timestamp.isoformat()}")
        return Candle(
            symbol=symbol,
            timeframe="5m",
            timestamp=self.timestamp,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.quote_volume,
        )


def gate_deals_archive_url(symbol: str, archive_month: str) -> str:
    if len(archive_month) != 6 or not archive_month.isdigit():
        raise ValueError("archive_month must use YYYYMM")
    pair = symbol.replace("/", "_").upper()
    return (
        f"{_BASE_URL}/spot/deals/{archive_month}/"
        f"{pair}-{archive_month}.csv.gz"
    )


def gate_deals_archive_available(
    symbol: str,
    archive_month: str,
    *,
    timeout_seconds: int = 30,
) -> tuple[bool, int | None]:
    url = gate_deals_archive_url(symbol, archive_month)
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "Trading-System-V3 historical-archive/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            length = response.headers.get("Content-Length")
            return response.status == 200, int(length) if length else None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, None
        raise ProviderError(f"Gate archive HEAD failed: {url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"Gate archive HEAD failed: {url}") from exc


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


def _hash_rows(candles: list[Candle]) -> str:
    payload = json.dumps(
        [_row(item) for item in candles],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def _month_bounds(archive_month: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(archive_month, "%Y%m").replace(tzinfo=timezone.utc)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _validate_range(start: datetime, end: datetime, archive_month: str) -> None:
    if start >= end:
        raise ValueError("start must be before end")
    month_start, month_end = _month_bounds(archive_month)
    if start < month_start or end > month_end:
        raise ValueError("archive shard must be contained in exactly one archive month")
    for timeframe in (*_TIMEFRAMES, "5m"):
        step = timeframe_seconds(timeframe)
        if int(start.timestamp()) % step or int(end.timestamp()) % step:
            raise ValueError(f"start/end must align to {timeframe}")


def _default_download(url: str, destination: Path, timeout_seconds: int) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Trading-System-V3 historical-archive/1.0"},
    )
    temp = destination.with_suffix(destination.suffix + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise ProviderError(
                    f"Gate archive download returned HTTP {response.status}: {url}"
                )
            with temp.open("wb") as handle:
                shutil.copyfileobj(response, handle, length=1024 * 1024)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(temp, destination)
    except urllib.error.HTTPError as exc:
        temp.unlink(missing_ok=True)
        raise ProviderError(f"Gate archive download failed: {url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        temp.unlink(missing_ok=True)
        raise ProviderError(f"Gate archive download failed: {url}") from exc


def _download_with_retries(
    url: str,
    destination: Path,
    *,
    policy: GateDealsArchivePolicy,
    sleep_fn: Callable[[float], None],
    downloader: ArchiveDownloader | None,
) -> None:
    for attempt in range(policy.max_retries + 1):
        try:
            if downloader is None:
                _default_download(url, destination, policy.timeout_seconds)
            else:
                downloader(url, destination)
            if not destination.exists() or destination.stat().st_size <= 0:
                raise ProviderError("Gate archive downloader produced an empty file")
            return
        except ProviderError:
            destination.unlink(missing_ok=True)
            if attempt >= policy.max_retries:
                raise
            sleep_fn(policy.retry_backoff_seconds * (2**attempt))
    raise RuntimeError("unreachable Gate archive retry state")


def _parse_archive_to_5m(
    path: Path,
    *,
    symbol: str,
    start: datetime,
    end: datetime,
) -> tuple[list[Candle], dict[str, object]]:
    start_decimal = Decimal(str(start.timestamp()))
    end_decimal = Decimal(str(end.timestamp()))
    buckets: dict[int, _FiveMinuteBucket] = {}
    seen_deal_ids: set[int] = set()
    total_rows = 0
    in_range_trades = 0

    try:
        handle = gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ProviderError("Gate archive is not valid gzip data") from exc

    try:
        with handle:
            reader = csv.reader(handle)
            for line_number, raw in enumerate(reader, start=1):
                if not raw:
                    continue
                total_rows += 1
                if line_number == 1 and [item.strip().lower() for item in raw] == [
                    "timestamp",
                    "dealid",
                    "price",
                    "amount",
                    "side",
                ]:
                    continue
                if len(raw) != 5:
                    raise ProviderError(
                        f"Gate deals archive row {line_number} has {len(raw)} fields; expected 5"
                    )
                try:
                    event_time = Decimal(raw[0])
                    deal_id = int(raw[1])
                    price = Decimal(raw[2])
                    base_amount = Decimal(raw[3])
                except (InvalidOperation, ValueError) as exc:
                    raise ProviderError(
                        f"Gate deals archive row {line_number} has invalid numeric data"
                    ) from exc
                side = raw[4].strip()
                if price <= 0 or base_amount < 0:
                    raise ProviderError(
                        f"Gate deals archive row {line_number} has invalid price/amount"
                    )
                if side not in {"1", "2"}:
                    raise ProviderError(
                        f"Gate deals archive row {line_number} has invalid side {side!r}"
                    )
                if event_time < start_decimal or event_time >= end_decimal:
                    continue
                if deal_id in seen_deal_ids:
                    raise ProviderError(f"duplicate Gate deal id in shard: {deal_id}")
                seen_deal_ids.add(deal_id)
                in_range_trades += 1

                whole_seconds = int(event_time)
                bucket_seconds = whole_seconds - (whole_seconds % _BASE_SECONDS)
                bucket = buckets.get(bucket_seconds)
                if bucket is None:
                    bucket = _FiveMinuteBucket(
                        datetime.fromtimestamp(bucket_seconds, tz=timezone.utc)
                    )
                    buckets[bucket_seconds] = bucket
                bucket.push(
                    event_key=(event_time, deal_id),
                    price=price,
                    base_amount=base_amount,
                )
    except (OSError, EOFError) as exc:
        raise ProviderError("Gate deals archive decompression failed") from exc

    if in_range_trades <= 0:
        raise ProviderError("Gate deals archive contains no trades in requested range")

    expected: list[int] = []
    cursor = int(start.timestamp())
    end_seconds = int(end.timestamp())
    while cursor < end_seconds:
        expected.append(cursor)
        cursor += _BASE_SECONDS
    missing = [stamp for stamp in expected if stamp not in buckets]
    unexpected = [stamp for stamp in buckets if stamp not in set(expected)]
    if missing:
        first_missing = datetime.fromtimestamp(missing[0], tz=timezone.utc)
        raise ProviderError(
            f"Gate deals reconstruction missing {len(missing)} 5m bucket(s); "
            f"first={first_missing.isoformat()}"
        )
    if unexpected:
        raise ProviderError("Gate deals reconstruction produced out-of-range 5m buckets")

    candles = [buckets[stamp].candle(symbol) for stamp in expected]
    quality = validate_candles(candles, expected_timeframe="5m")
    if not quality.valid:
        raise ProviderError("reconstructed 5m validation failed: " + "; ".join(quality.reasons))
    evidence: dict[str, object] = {
        "archive_total_rows": total_rows,
        "in_range_trade_rows": in_range_trades,
        "base_5m_candle_count": len(candles),
    }
    return candles, evidence


def _aggregate(base: list[Candle], timeframe: str) -> list[Candle]:
    step = timeframe_seconds(timeframe)
    if step % _BASE_SECONDS:
        raise ValueError(f"timeframe is not divisible by 5m: {timeframe}")
    child_count = step // _BASE_SECONDS
    if len(base) % child_count:
        raise ProviderError(f"5m candle count does not align to {timeframe}")

    output: list[Candle] = []
    for offset in range(0, len(base), child_count):
        children = base[offset : offset + child_count]
        first = children[0]
        expected_start = int(first.timestamp.timestamp())
        if expected_start % step:
            raise ProviderError(f"5m source is not aligned to {timeframe}")
        for index, child in enumerate(children):
            expected = first.timestamp + timedelta(seconds=_BASE_SECONDS * index)
            if child.timestamp != expected:
                raise ProviderError(f"non-contiguous 5m children for {timeframe}")
        output.append(
            Candle(
                symbol=first.symbol,
                timeframe=timeframe,
                timestamp=first.timestamp,
                open=first.open,
                high=max(item.high for item in children),
                low=min(item.low for item in children),
                close=children[-1].close,
                volume=sum((item.volume for item in children), Decimal("0")),
            )
        )

    quality = validate_candles(output, expected_timeframe=timeframe)
    if not quality.valid:
        raise ProviderError(
            f"reconstructed {timeframe} validation failed: " + "; ".join(quality.reasons)
        )
    return output


def collect_gate_deals_archive_dataset(
    *,
    symbol: str,
    archive_month: str,
    start: datetime,
    end: datetime,
    output_dir: str | Path,
    dataset_version: str,
    policy: GateDealsArchivePolicy | None = None,
    code_revision: str = "UNKNOWN",
    sleep_fn: Callable[[float], None] = time.sleep,
    downloader: ArchiveDownloader | None = None,
) -> LockedDatasetBundle:
    start_utc = _utc(start, "start")
    end_utc = _utc(end, "end")
    _validate_range(start_utc, end_utc, archive_month)
    applied = policy or GateDealsArchivePolicy()
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        return load_locked_dataset(root)

    url = gate_deals_archive_url(symbol, archive_month)
    work_dir = root / ".work"
    archive_path = work_dir / f"{archive_month}.csv.gz"
    retrieved_at = datetime.now(timezone.utc)
    _download_with_retries(
        url,
        archive_path,
        policy=applied,
        sleep_fn=sleep_fn,
        downloader=downloader,
    )
    archive_sha = _file_sha(archive_path)
    archive_bytes = archive_path.stat().st_size

    try:
        base_5m, parse_evidence = _parse_archive_to_5m(
            archive_path,
            symbol=symbol,
            start=start_utc,
            end=end_utc,
        )
        candles_by_timeframe = {
            timeframe: _aggregate(base_5m, timeframe)
            for timeframe in _TIMEFRAMES
        }

        source_evidence: dict[str, object] = {
            "source_kind": "gateio_spot_deals_archive",
            "archive_month": archive_month,
            "source_uri": url,
            "retrieved_at": retrieved_at.isoformat(),
            "compressed_sha256": archive_sha,
            "compressed_bytes": archive_bytes,
            "deal_schema": ["timestamp", "dealid", "price", "amount", "side"],
            "amount_semantics": "base_currency",
            "candle_volume_semantics": "quote_currency=sum(price*base_amount)",
            **parse_evidence,
        }

        timeframe_entries: dict[str, object] = {}
        content_hashes: dict[str, str] = {}
        for timeframe, candles in candles_by_timeframe.items():
            provenance = DatasetProvenance(
                provider="gateio",
                provider_symbol=symbol.replace("/", "_").upper(),
                retrieved_at=retrieved_at,
                source_uri=url,
                license_id="gateio-public-historical-archive",
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
            if dataset.content_sha256 != _hash_rows(candles):
                raise RuntimeError("Gate archive dataset canonical hash mismatch")
            locked_path = root / "locked" / _slug(symbol) / f"{timeframe}.jsonl"
            locked_sha = _write_locked(locked_path, candles)
            content_hashes[timeframe] = dataset.content_sha256
            timeframe_entries[timeframe] = {
                "dataset": dataset.to_manifest(),
                "locked_file": locked_path.relative_to(root).as_posix(),
                "locked_file_sha256": locked_sha,
                "checkpoint_chunks": [source_evidence],
            }

        stable_identity: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "provider": "gateio",
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
                "source_kind": "gateio_spot_deals_archive",
                "archive_month": archive_month,
                "base_reconstruction_timeframe": "5m",
                "max_retries": applied.max_retries,
                "retry_backoff_seconds": applied.retry_backoff_seconds,
                "timeout_seconds": applied.timeout_seconds,
            },
            "archive_source": source_evidence,
            "dataset_bundle_fingerprint": _fingerprint(stable_identity),
            "timeframes": timeframe_entries,
        }
        manifest["manifest_fingerprint"] = _fingerprint(manifest)
        _atomic_json(manifest_path, manifest)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return load_locked_dataset(root)
