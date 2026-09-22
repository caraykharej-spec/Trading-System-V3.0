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
import struct
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as wall_time, timedelta, timezone
from decimal import Decimal, InvalidOperation
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


def _request_bytes(url: str, *, attempts: int = 5) -> bytes:
    delay = 1.0
    for attempt in range(1, attempts + 1):
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
            if exc.code == 404:
                return b""
            retryable = exc.code in {408, 429} or 500 <= exc.code < 600
            if not retryable or attempt == attempts:
                raise ProviderError(f"historical data HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == attempts:
                raise ProviderError("historical data request failed") from exc
        time.sleep(delay)
        delay = min(delay * 2, 20.0)
    raise AssertionError("unreachable")


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
        seconds, open_raw, high_raw, low_raw, close_raw, volume_raw = (
            _DUKASCOPY_RECORD.unpack_from(raw, offset)
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
        compressed = _request_bytes(_dukascopy_url(route, day))
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
    quality = {
        "invalid_rows_dropped": 0,
        "ohlc_invariant_rows_dropped": 0,
        "out_of_session_rows_dropped": 0,
        "source_days_without_rows": 0,
    }
    if route.provider == "alpaca_sip":
        fifteen = fetch_alpaca_15m(route, start=start, end=end, quality=quality)
    elif route.provider == "dukascopy":
        fifteen = fetch_dukascopy_15m(route, start=start, end=end, quality=quality)
    else:
        raise ValueError(f"unsupported provider: {route.provider}")
    _validate_coverage(route, fifteen, start=start)
    datasets = {
        "15m": fifteen,
        "1h": aggregate_candles(fifteen, "1h", session=route.session),
        "4h": aggregate_candles(fifteen, "4h", session=route.session),
        "1d": aggregate_candles(fifteen, "1d", session=route.session),
    }
    if any(not rows for rows in datasets.values()):
        missing = [timeframe for timeframe, rows in datasets.items() if not rows]
        raise ProviderError(f"derived history is empty for: {','.join(missing)}")

    partitions: list[Partition] = []
    coverage: dict[str, object] = {}
    for timeframe, rows in datasets.items():
        coverage[timeframe] = {
            "rows": len(rows),
            "first_timestamp": rows[0].timestamp.isoformat(),
            "last_timestamp": rows[-1].timestamp.isoformat(),
        }
        for year, year_rows in _year_groups(rows):
            partitions.append(
                _store_partition(route, timeframe, year, year_rows, force=force)
            )

    manifest: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "COMPLETE",
        "route": {
            "canonical_symbol": route.base_asset,
            "base_asset": route.base_asset,
            "asset_class": route.asset_class,
            "provider": route.provider,
            "provider_symbol": route.symbol,
            "price_multiplier": str(route.price_multiplier),
            "requires_volume": route.asset_class == "equity",
            "route_origin": "historical_15m_repair_registry",
        },
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
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
