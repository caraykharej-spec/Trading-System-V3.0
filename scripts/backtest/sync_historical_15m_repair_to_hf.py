"""Repair source-limited non-crypto 15m history in the private research store.

US equities use delayed historical Alpaca SIP bars. Forex, metals, Brent and
the reviewed SPX CFD proxy use Dukascopy BID minute candles aggregated without
forward filling. The live market-data route order is intentionally unchanged.
"""

from __future__ import annotations

import argparse
import json
import lzma
import math
import os
import random
import struct
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as wall_time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from app.data.historical_15m_registry import Historical15mRegistry, Historical15mRoute
from app.data.providers.http import ProviderError
from scripts.backtest import hf_s3
from scripts.backtest import sync_yahoo_history_to_hf as storage

_ALPACA_BASE = "https://data.alpaca.markets/v2/stocks"
_DUKASCOPY_BASE = "https://datafeed.dukascopy.com/datafeed"
_NAMESPACE = "bronze/historical-15m-repair/v1"
_MANIFEST_NAMESPACE = "manifests/historical-15m-repair/v1"
_SCHEMA_VERSION = 1
_DUKASCOPY_RECORD = struct.Struct(">5If")
_US_EASTERN = ZoneInfo("America/New_York")
_TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None


@dataclass(frozen=True)
class Partition:
    timeframe: str
    year: int
    rows: int
    object_key: str
    sha256: str
    first_timestamp: str
    last_timestamp: str
    reused_verified: bool


def discover_routes() -> list[Historical15mRoute]:
    return list(Historical15mRegistry.load().all())


def _positive_env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    value = float(raw) if raw else default
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _positive_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    value = int(raw) if raw else default
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _retry_after_seconds(exc: urllib.error.HTTPError, *, now: datetime | None = None) -> float:
    value = exc.headers.get("Retry-After") if exc.headers is not None else None
    if not value:
        return 0.0
    text = value.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        return max(0.0, (parsed.astimezone(timezone.utc) - current).total_seconds())


def _retry_delay(attempt: int, exc: BaseException | None = None) -> float:
    base = _positive_env_float("DUKASCOPY_RETRY_BASE_SECONDS", 2.0)
    maximum = _positive_env_float("DUKASCOPY_RETRY_MAX_SECONDS", 60.0)
    jitter_cap = _positive_env_float("DUKASCOPY_RETRY_JITTER_SECONDS", 1.0)
    exponential = min(maximum, base * (2 ** (attempt - 1)))
    retry_after = _retry_after_seconds(exc) if isinstance(exc, urllib.error.HTTPError) else 0.0
    return max(exponential, retry_after) + random.uniform(0.0, jitter_cap)


def _request_bytes(
    url: str,
    *,
    attempts: int | None = None,
    transport_attempts: int | None = None,
) -> bytes:
    http_budget = attempts or _positive_env_int("DUKASCOPY_HTTP_ATTEMPTS", 7)
    transport_budget = transport_attempts or (
        attempts or _positive_env_int("DUKASCOPY_TRANSPORT_ATTEMPTS", 10)
    )
    http_failures = 0
    transport_failures = 0
    while True:
        failure: BaseException | None = None
        retry_number = 0
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Trading-System-V3 historical-15m-repair/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status != 200:
                    raise ProviderError(f"historical data HTTP {response.status}")
                return response.read()
        except urllib.error.HTTPError as exc:
            failure = exc
            if exc.code == 404:
                return b""
            retryable = exc.code in _TRANSIENT_HTTP_STATUS
            http_failures += 1
            if not retryable or http_failures >= http_budget:
                raise ProviderError(f"historical data HTTP {exc.code}") from exc
            retry_number = http_failures
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failure = exc
            transport_failures += 1
            if transport_failures >= transport_budget:
                raise ProviderError("historical data request failed") from exc
            retry_number = transport_failures
        time.sleep(_retry_delay(retry_number, failure))


def _pace_dukascopy_request() -> None:
    delay = _positive_env_float("DUKASCOPY_REQUEST_INTERVAL_SECONDS", 0.2)
    if delay:
        time.sleep(delay)


def _request_alpaca_json(url: str, *, attempts: int = 6) -> dict[str, object]:
    key = os.environ.get("ALPACA_API_KEY_ID", "").strip()
    secret = os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are required")
    delay = 1.0
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "APCA-API-KEY-ID": key,
                "APCA-API-SECRET-KEY": secret,
                "User-Agent": "Trading-System-V3 historical-15m-repair/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ProviderError("Alpaca response is not an object")
            return payload
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {408, 429} or 500 <= exc.code < 600
            if not retryable or attempt == attempts:
                raise ProviderError(f"Alpaca HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            if attempt == attempts:
                raise ProviderError("Alpaca request or response failed") from exc
        time.sleep(delay)
        delay = min(delay * 2, 30.0)
    raise AssertionError("unreachable")


def _parse_decimal(value: object, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ProviderError(f"invalid {field} value") from exc
    if not parsed.is_finite():
        raise ProviderError(f"non-finite {field} value")
    return parsed


def _valid_candle(candle: Candle) -> bool:
    return (
        candle.low <= candle.high
        and candle.low <= candle.open <= candle.high
        and candle.low <= candle.close <= candle.high
    )


def _is_us_rth(timestamp: datetime) -> bool:
    local = timestamp.astimezone(_US_EASTERN)
    value = local.timetz().replace(tzinfo=None)
    return local.weekday() < 5 and wall_time(9, 30) <= value < wall_time(16, 0)


def fetch_alpaca_15m(
    route: Historical15mRoute,
    *,
    start: datetime,
    end: datetime,
    quality: dict[str, int],
) -> list[Candle]:
    effective_end = min(end, datetime.now(timezone.utc) - timedelta(minutes=16))
    if effective_end <= start:
        raise ProviderError("Alpaca effective end must be later than start")
    rows: dict[datetime, Candle] = {}
    token: str | None = None
    while True:
        query: dict[str, str] = {
            "timeframe": "15Min",
            "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end": effective_end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "adjustment": "all",
            "feed": "sip",
            "sort": "asc",
            "limit": "10000",
        }
        if token:
            query["page_token"] = token
        url = f"{_ALPACA_BASE}/{urllib.parse.quote(route.symbol, safe='')}/bars?{urllib.parse.urlencode(query)}"
        payload = _request_alpaca_json(url)
        raw_bars = payload.get("bars") or []
        if not isinstance(raw_bars, list):
            raise ProviderError("Alpaca bars field is not a list")
        for raw in raw_bars:
            if not isinstance(raw, dict):
                quality["invalid_rows_dropped"] += 1
                continue
            try:
                timestamp = datetime.fromisoformat(str(raw["t"]).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("naive timestamp")
                timestamp = timestamp.astimezone(timezone.utc)
                if route.session == "us_rth" and not _is_us_rth(timestamp):
                    quality["out_of_session_rows_dropped"] += 1
                    continue
                multiplier = route.price_multiplier
                candle = Candle(
                    timestamp=timestamp,
                    open=_parse_decimal(raw["o"], "open") * multiplier,
                    high=_parse_decimal(raw["h"], "high") * multiplier,
                    low=_parse_decimal(raw["l"], "low") * multiplier,
                    close=_parse_decimal(raw["c"], "close") * multiplier,
                    volume=_parse_decimal(raw["v"], "volume") if raw.get("v") is not None else None,
                )
            except (KeyError, TypeError, ValueError, ProviderError):
                quality["invalid_rows_dropped"] += 1
                continue
            if not _valid_candle(candle):
                quality["ohlc_invariant_rows_dropped"] += 1
                continue
            prior = rows.get(timestamp)
            if prior is not None and prior != candle:
                raise ProviderError(f"Alpaca conflicting duplicate at {timestamp.isoformat()}")
            rows[timestamp] = candle
        next_token = payload.get("next_page_token")
        if not next_token:
            break
        token = str(next_token)
    return [rows[key] for key in sorted(rows)]


def _dukascopy_url(route: Historical15mRoute, day: date) -> str:
    # Dukascopy uses zero-based month directories.
    return (
        f"{_DUKASCOPY_BASE}/{route.symbol}/{day.year:04d}/{day.month - 1:02d}/"
        f"{day.day:02d}/BID_candles_min_1.bi5"
    )


def parse_dukascopy_day(
    compressed: bytes,
    route: Historical15mRoute,
    day: date,
    *,
    quality: dict[str, int],
) -> list[Candle]:
    if not compressed:
        return []
    try:
        raw = lzma.decompress(compressed)
    except lzma.LZMAError as exc:
        raise ProviderError(f"invalid Dukascopy BI5 payload for {day.isoformat()}") from exc
    if len(raw) % _DUKASCOPY_RECORD.size:
        raise ProviderError(f"invalid Dukascopy record length for {day.isoformat()}")
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    output: list[Candle] = []
    for offset in range(0, len(raw), _DUKASCOPY_RECORD.size):
        seconds, open_raw, high_raw, low_raw, close_raw, volume_raw = _DUKASCOPY_RECORD.unpack_from(
            raw, offset
        )
        if seconds >= 86_400 or not math.isfinite(volume_raw):
            quality["invalid_rows_dropped"] += 1
            continue
        scale = route.price_multiplier / route.price_divisor
        candle = Candle(
            timestamp=start + timedelta(seconds=seconds),
            open=Decimal(open_raw) * scale,
            high=Decimal(high_raw) * scale,
            low=Decimal(low_raw) * scale,
            close=Decimal(close_raw) * scale,
            volume=Decimal(str(volume_raw)),
        )
        if not _valid_candle(candle):
            quality["ohlc_invariant_rows_dropped"] += 1
            continue
        output.append(candle)
    return output


def _date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def fetch_dukascopy_15m(
    route: Historical15mRoute,
    *,
    start: datetime,
    end: datetime,
    quality: dict[str, int],
) -> list[Candle]:
    minutes: dict[datetime, Candle] = {}
    final_day = (end - timedelta(microseconds=1)).date()
    for day in _date_range(start.date(), final_day):
        try:
            compressed = _request_bytes(_dukascopy_url(route, day))
        except ProviderError as exc:
            raise ProviderError(
                f"Dukascopy {route.base_asset}/{route.symbol} failed on {day.isoformat()}: {exc}"
            ) from exc
        _pace_dukascopy_request()
        daily = parse_dukascopy_day(compressed, route, day, quality=quality)
        if not daily:
            quality["source_days_without_rows"] += 1
        for candle in daily:
            if candle.timestamp < start or candle.timestamp >= end:
                continue
            prior = minutes.get(candle.timestamp)
            if prior is not None and prior != candle:
                raise ProviderError(
                    f"Dukascopy conflicting duplicate at {candle.timestamp.isoformat()}"
                )
            minutes[candle.timestamp] = candle
    return aggregate_candles(list(minutes.values()), "15m", session="utc")


def _bucket_start(timestamp: datetime, timeframe: str, session: str) -> datetime:
    if session == "us_rth":
        local = timestamp.astimezone(_US_EASTERN)
        session_open = local.replace(hour=9, minute=30, second=0, microsecond=0)
        elapsed = int((local - session_open).total_seconds())
        if timeframe == "1d":
            return session_open.astimezone(timezone.utc)
        seconds = 3_600 if timeframe == "1h" else 14_400
        return (session_open + timedelta(seconds=(elapsed // seconds) * seconds)).astimezone(
            timezone.utc
        )
    epoch = int(timestamp.timestamp())
    seconds = {"15m": 900, "1h": 3_600, "4h": 14_400, "1d": 86_400}[timeframe]
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=timezone.utc)


def aggregate_candles(rows: list[Candle], timeframe: str, *, session: str) -> list[Candle]:
    buckets: dict[datetime, list[Candle]] = {}
    for row in rows:
        buckets.setdefault(_bucket_start(row.timestamp, timeframe, session), []).append(row)
    output: list[Candle] = []
    for bucket, group in sorted(buckets.items()):
        ordered = sorted(group, key=lambda item: item.timestamp)
        volumes = [item.volume for item in ordered if item.volume is not None]
        output.append(
            Candle(
                timestamp=bucket,
                open=ordered[0].open,
                high=max(item.high for item in ordered),
                low=min(item.low for item in ordered),
                close=ordered[-1].close,
                volume=sum(volumes, Decimal("0")) if volumes else None,
            )
        )
    return output


def _year_groups(rows: list[Candle]) -> Iterable[tuple[int, list[Candle]]]:
    groups: dict[int, list[Candle]] = {}
    for row in rows:
        groups.setdefault(row.timestamp.year, []).append(row)
    for year in sorted(groups):
        yield year, sorted(groups[year], key=lambda item: item.timestamp)


def _source_kind(route: Historical15mRoute) -> str:
    if route.provider == "alpaca_sip":
        return "alpaca_historical_sip_adjusted_all_us_rth"
    return "dukascopy_public_bid_m1_aggregated_no_fill"


def _write_parquet(
    path: Path,
    route: Historical15mRoute,
    timeframe: str,
    rows: list[Candle],
) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required; install the research-data extra") from exc
    table = pa.table(
        {
            "canonical_symbol": [route.base_asset] * len(rows),
            "provider": [route.provider] * len(rows),
            "provider_symbol": [route.symbol] * len(rows),
            "asset_class": [route.asset_class] * len(rows),
            "timeframe": [timeframe] * len(rows),
            "timestamp": [item.timestamp for item in rows],
            "open": [str(item.open) for item in rows],
            "high": [str(item.high) for item in rows],
            "low": [str(item.low) for item in rows],
            "close": [str(item.close) for item in rows],
            "adjusted_close": [str(item.close) for item in rows],
            "volume": [str(item.volume) if item.volume is not None else None for item in rows],
            "price_multiplier": [str(route.price_multiplier)] * len(rows),
            "source_kind": [_source_kind(route)] * len(rows),
        }
    )
    pq.write_table(table, path, compression="zstd", version="2.6")


def _partition_key(route: Historical15mRoute, timeframe: str, year: int) -> str:
    return (
        f"{_NAMESPACE}/provider={storage._slug(route.provider)}/"
        f"canonical={storage._slug(route.base_asset)}/market={storage._slug(route.symbol)}/"
        f"timeframe={timeframe}/year={year:04d}/part-000.parquet"
    )


def _store_partition(
    route: Historical15mRoute,
    timeframe: str,
    year: int,
    rows: list[Candle],
    *,
    force: bool,
) -> Partition:
    key = _partition_key(route, timeframe, year)
    with tempfile.TemporaryDirectory(prefix="historical-15m-repair-") as temp_dir:
        path = Path(temp_dir) / "part-000.parquet"
        _write_parquet(path, route, timeframe, rows)
        digest = storage._sha256(path)
        existing = storage._remote_sha256(key)
        reused = existing == digest and not force
        if not reused:
            storage._put_verified(path, key, digest, "application/vnd.apache.parquet")
    return Partition(
        timeframe=timeframe,
        year=year,
        rows=len(rows),
        object_key=key,
        sha256=digest,
        first_timestamp=rows[0].timestamp.isoformat(),
        last_timestamp=rows[-1].timestamp.isoformat(),
        reused_verified=reused,
    )


def _route_identity(route: Historical15mRoute) -> dict[str, object]:
    return {
        "canonical_symbol": route.base_asset,
        "base_asset": route.base_asset,
        "asset_class": route.asset_class,
        "provider": route.provider,
        "provider_symbol": route.symbol,
        "price_multiplier": str(route.price_multiplier),
        "requires_volume": route.asset_class == "equity",
        "route_origin": "historical_15m_repair_registry",
    }


def _checkpoint_key(route: Historical15mRoute, year: int) -> str:
    return (
        f"{_MANIFEST_NAMESPACE}/checkpoints/provider={storage._slug(route.provider)}/"
        f"canonical={storage._slug(route.base_asset)}/market={storage._slug(route.symbol)}/"
        f"year={year:04d}.json"
    )


def _load_remote_json(key: str) -> dict[str, object] | None:
    with tempfile.TemporaryDirectory(prefix="historical-15m-checkpoint-") as temp_dir:
        target = Path(temp_dir) / "checkpoint.json"
        result = storage._aws(
            "s3api",
            "get-object",
            "--bucket",
            storage._bucket(),
            "--key",
            key,
            str(target),
            check=False,
        )
        if storage._missing(result):
            return None
        payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProviderError(f"checkpoint is not a JSON object: {key}")
    return payload


def _partition_from_checkpoint(raw: object) -> Partition:
    if not isinstance(raw, dict):
        raise ValueError("checkpoint partition must be an object")
    return Partition(
        timeframe=str(raw["timeframe"]),
        year=int(raw["year"]),
        rows=int(raw["rows"]),
        object_key=str(raw["object_key"]),
        sha256=str(raw["sha256"]),
        first_timestamp=str(raw["first_timestamp"]),
        last_timestamp=str(raw["last_timestamp"]),
        reused_verified=True,
    )


def _load_valid_year_checkpoint(
    route: Historical15mRoute,
    *,
    year: int,
    start: datetime,
    end: datetime,
    force: bool,
) -> tuple[list[Partition], dict[str, int]] | None:
    if force:
        return None
    key = _checkpoint_key(route, year)
    checkpoint = _load_remote_json(key)
    if checkpoint is None:
        return None
    expected = _route_identity(route)
    actual_route = checkpoint.get("route")
    if (
        checkpoint.get("status") != "COMPLETE_YEAR_CHECKPOINT"
        or actual_route != expected
        or checkpoint.get("range_start") != start.isoformat()
        or checkpoint.get("range_end") != end.isoformat()
    ):
        return None
    try:
        partitions = [_partition_from_checkpoint(item) for item in checkpoint.get("partitions", [])]
    except (KeyError, TypeError, ValueError):
        return None
    if (
        len(partitions) != 4
        or {item.timeframe for item in partitions} != {"15m", "1h", "4h", "1d"}
        or any(item.year != year or item.rows <= 0 for item in partitions)
    ):
        return None
    for partition in partitions:
        if len(partition.sha256) != 64:
            return None
        if storage._remote_sha256(partition.object_key) != partition.sha256:
            return None
    raw_quality = checkpoint.get("quality")
    if not isinstance(raw_quality, dict):
        return None
    quality = {
        name: int(raw_quality.get(name) or 0)
        for name in (
            "invalid_rows_dropped",
            "ohlc_invariant_rows_dropped",
            "out_of_session_rows_dropped",
            "source_days_without_rows",
        )
    }
    return partitions, quality


def _write_year_checkpoint(
    route: Historical15mRoute,
    *,
    year: int,
    start: datetime,
    end: datetime,
    quality: dict[str, int],
    partitions: list[Partition],
) -> str:
    key = _checkpoint_key(route, year)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "status": "COMPLETE_YEAR_CHECKPOINT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "route": _route_identity(route),
        "year": year,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "quality": quality,
        "integrity_policy": "all_partition_sha256_read_back_verified_before_checkpoint",
        "partitions": [asdict(item) for item in partitions],
    }
    storage._put_json(payload, key)
    return key


def _empty_quality() -> dict[str, int]:
    return {
        "invalid_rows_dropped": 0,
        "ohlc_invariant_rows_dropped": 0,
        "out_of_session_rows_dropped": 0,
        "source_days_without_rows": 0,
    }


def _add_quality(target: dict[str, int], source: dict[str, int]) -> None:
    for name in target:
        target[name] += int(source.get(name, 0))


def _coverage_from_partitions(partitions: list[Partition]) -> dict[str, object]:
    coverage: dict[str, object] = {}
    for timeframe in ("15m", "1h", "4h", "1d"):
        selected = [item for item in partitions if item.timeframe == timeframe]
        if not selected:
            continue
        coverage[timeframe] = {
            "rows": sum(item.rows for item in selected),
            "first_timestamp": min(item.first_timestamp for item in selected),
            "last_timestamp": max(item.last_timestamp for item in selected),
        }
    return coverage


def _year_ranges(start: datetime, end: datetime) -> Iterable[tuple[int, datetime, datetime]]:
    year = start.year
    while year <= (end - timedelta(microseconds=1)).year:
        year_start = datetime(year, 1, 1, tzinfo=timezone.utc)
        next_year = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        chunk_start = max(start, year_start)
        chunk_end = min(end, next_year)
        if chunk_start < chunk_end:
            yield year, chunk_start, chunk_end
        year += 1


def _validate_coverage(
    route: Historical15mRoute,
    rows: list[Candle],
    *,
    start: datetime,
) -> None:
    if not rows:
        raise ProviderError("source returned no valid 15m history")
    if route.listing_limited:
        return
    span_days = (rows[-1].timestamp - rows[0].timestamp).days
    if span_days < route.minimum_history_days:
        raise ProviderError(
            f"15m history span is {span_days} days; required {route.minimum_history_days}"
        )
    if rows[0].timestamp > start + timedelta(days=14):
        raise ProviderError("15m history begins materially after the reviewed requested start")


def _datasets_from_fifteen(
    route: Historical15mRoute, fifteen: list[Candle]
) -> dict[str, list[Candle]]:
    datasets = {
        "15m": fifteen,
        "1h": aggregate_candles(fifteen, "1h", session=route.session),
        "4h": aggregate_candles(fifteen, "4h", session=route.session),
        "1d": aggregate_candles(fifteen, "1d", session=route.session),
    }
    missing = [timeframe for timeframe, rows in datasets.items() if not rows]
    if missing:
        raise ProviderError(f"derived history is empty for: {','.join(missing)}")
    return datasets


def _validate_partition_coverage(
    route: Historical15mRoute, partitions: list[Partition], *, start: datetime
) -> None:
    fifteen = sorted(
        (item for item in partitions if item.timeframe == "15m"),
        key=lambda item: item.first_timestamp,
    )
    if not fifteen:
        raise ProviderError("source returned no valid 15m history")
    if route.listing_limited:
        return
    first = datetime.fromisoformat(fifteen[0].first_timestamp)
    last = datetime.fromisoformat(fifteen[-1].last_timestamp)
    span_days = (last - first).days
    if span_days < route.minimum_history_days:
        raise ProviderError(
            f"15m history span is {span_days} days; required {route.minimum_history_days}"
        )
    if first > start + timedelta(days=14):
        raise ProviderError("15m history begins materially after the reviewed requested start")


def _sync_dukascopy_incremental(
    route: Historical15mRoute,
    *,
    start: datetime,
    end: datetime,
    force: bool,
) -> dict[str, object]:
    quality = _empty_quality()
    partitions: list[Partition] = []
    checkpoint_keys: list[str] = []
    checkpoint_years_reused = 0
    checkpoint_years_written = 0

    for year, chunk_start, chunk_end in _year_ranges(start, end):
        cached = _load_valid_year_checkpoint(
            route, year=year, start=chunk_start, end=chunk_end, force=force
        )
        if cached is not None:
            year_partitions, year_quality = cached
            partitions.extend(year_partitions)
            _add_quality(quality, year_quality)
            checkpoint_keys.append(_checkpoint_key(route, year))
            checkpoint_years_reused += 1
            continue

        year_quality = _empty_quality()
        fifteen = fetch_dukascopy_15m(route, start=chunk_start, end=chunk_end, quality=year_quality)
        if not fifteen:
            raise ProviderError(
                f"Dukascopy {route.base_asset}/{route.symbol} returned no valid rows "
                f"for {chunk_start.date()}..{chunk_end.date()}"
            )
        datasets = _datasets_from_fifteen(route, fifteen)
        year_partitions = [
            _store_partition(route, timeframe, year, rows, force=force)
            for timeframe, rows in datasets.items()
        ]
        checkpoint_keys.append(
            _write_year_checkpoint(
                route,
                year=year,
                start=chunk_start,
                end=chunk_end,
                quality=year_quality,
                partitions=year_partitions,
            )
        )
        checkpoint_years_written += 1
        partitions.extend(year_partitions)
        _add_quality(quality, year_quality)

    _validate_partition_coverage(route, partitions, start=start)
    manifest: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "COMPLETE",
        "route": _route_identity(route),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "source_kind": _source_kind(route),
        "qualification_scope": "research_backtest_only_live_route_order_unchanged",
        "history_policy": "provider_backed_15m_with_1h_4h_1d_deterministically_derived",
        "session_policy": route.session,
        "adjustment_policy": "dukascopy_bid_m1_source_no_forward_fill",
        "proxy_for": route.proxy_for,
        "listing_limited": route.listing_limited,
        "gap_policy": "preserve_source_market_sessions_no_fill",
        "invalid_source_row_policy": "drop_and_record_never_clamp",
        "quality": quality,
        "source_ohlc_invariant_rows_dropped": quality["ohlc_invariant_rows_dropped"],
        "coverage": _coverage_from_partitions(partitions),
        "total_rows": sum(item.rows for item in partitions),
        "partition_objects_recorded": len(partitions),
        "reused_verified_partition_objects": sum(item.reused_verified for item in partitions),
        "uploaded_or_replaced_partition_objects": sum(
            not item.reused_verified for item in partitions
        ),
        "integrity_policy": "sha256_manifest_compare_upload_verify_downloaded_bytes",
        "checkpoint_policy": "per_year_sha256_verified_resume",
        "checkpoint_years_reused": checkpoint_years_reused,
        "checkpoint_years_written": checkpoint_years_written,
        "checkpoint_manifest_keys": checkpoint_keys,
        "partitions": [asdict(item) for item in partitions],
    }
    manifest_key = (
        f"{_MANIFEST_NAMESPACE}/routes/provider={storage._slug(route.provider)}/"
        f"canonical={storage._slug(route.base_asset)}/market={storage._slug(route.symbol)}.json"
    )
    storage._put_json(manifest, manifest_key)
    manifest["manifest_object_key"] = manifest_key
    return manifest


def sync_route(
    route: Historical15mRoute,
    *,
    start: datetime,
    end: datetime,
    force: bool = False,
) -> dict[str, object]:
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("start/end must be timezone-aware and end must be later than start")
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if route.provider == "dukascopy":
        return _sync_dukascopy_incremental(route, start=start, end=end, force=force)

    quality = _empty_quality()
    if route.provider == "alpaca_sip":
        fifteen = fetch_alpaca_15m(route, start=start, end=end, quality=quality)
    else:
        raise ValueError(f"unsupported provider: {route.provider}")
    _validate_coverage(route, fifteen, start=start)
    datasets = _datasets_from_fifteen(route, fifteen)

    partitions: list[Partition] = []
    coverage: dict[str, object] = {}
    for timeframe, rows in datasets.items():
        coverage[timeframe] = {
            "rows": len(rows),
            "first_timestamp": rows[0].timestamp.isoformat(),
            "last_timestamp": rows[-1].timestamp.isoformat(),
        }
        for year, year_rows in _year_groups(rows):
            partitions.append(_store_partition(route, timeframe, year, year_rows, force=force))

    manifest: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "COMPLETE",
        "route": _route_identity(route),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "source_kind": _source_kind(route),
        "qualification_scope": "research_backtest_only_live_route_order_unchanged",
        "history_policy": "provider_backed_15m_with_1h_4h_1d_deterministically_derived",
        "session_policy": route.session,
        "adjustment_policy": (
            "alpaca_adjustment_all_feed_sip_regular_trading_hours_only"
            if route.provider == "alpaca_sip"
            else "dukascopy_bid_m1_source_no_forward_fill"
        ),
        "proxy_for": route.proxy_for,
        "listing_limited": route.listing_limited,
        "gap_policy": "preserve_source_market_sessions_no_fill",
        "invalid_source_row_policy": "drop_and_record_never_clamp",
        "quality": quality,
        "source_ohlc_invariant_rows_dropped": quality["ohlc_invariant_rows_dropped"],
        "coverage": coverage,
        "total_rows": sum(len(rows) for rows in datasets.values()),
        "partition_objects_recorded": len(partitions),
        "reused_verified_partition_objects": sum(item.reused_verified for item in partitions),
        "uploaded_or_replaced_partition_objects": sum(
            not item.reused_verified for item in partitions
        ),
        "integrity_policy": "sha256_manifest_compare_upload_verify_downloaded_bytes",
        "partitions": [asdict(item) for item in partitions],
    }
    manifest_key = (
        f"{_MANIFEST_NAMESPACE}/routes/provider={storage._slug(route.provider)}/"
        f"canonical={storage._slug(route.base_asset)}/market={storage._slug(route.symbol)}.json"
    )
    storage._put_json(manifest, manifest_key)
    manifest["manifest_object_key"] = manifest_key
    return manifest


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SystemExit("timestamps must include timezone")
    return parsed.astimezone(timezone.utc)


def main() -> int:
    storage._aws = hf_s3.aws
    parser = argparse.ArgumentParser(
        description="Repair non-crypto 15m backtest history using Alpaca SIP and Dukascopy"
    )
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--base-asset")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    registry = Historical15mRegistry.load()
    if args.discover_only:
        routes = registry.all()
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "route_count": len(routes),
            "routes": [asdict(route) for route in routes],
        }
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return 0
    if not args.base_asset:
        raise SystemExit("route mode requires --base-asset")
    route = registry.get(args.base_asset)
    if route is None:
        raise SystemExit(f"historical 15m repair route not found: {args.base_asset}")
    start = _parse_datetime(args.start) if args.start else route.start
    end = _parse_datetime(args.end) if args.end else datetime.now(timezone.utc)
    try:
        payload = sync_route(route, start=start, end=end, force=args.force)
    except Exception as exc:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "status": "ERROR",
            "route": {
                "base_asset": route.base_asset,
                "asset_class": route.asset_class,
                "provider": route.provider,
                "provider_symbol": route.symbol,
                "price_multiplier": str(route.price_multiplier),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partitions": [],
        }
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
