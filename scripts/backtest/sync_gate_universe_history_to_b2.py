from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from app.data.market_data import Candle
from app.data.providers.gateio import GateIOProvider
from app.data.providers.gateio_futures import GateIOFuturesProvider
from app.data.providers.http import ProviderError, to_decimal
from app.data.source_registry import SourceMappingRegistry
from app.universe.gateio_discovery import GateIOSpotDiscoveryProvider
from app.universe.scope import is_project_base_asset
from app.universe.storm_discovery import StormReferenceUniverseProvider

_TIMEFRAMES = ("15m", "1h", "4h", "1d")
_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
_FULL_HISTORY_PROVIDERS = {"gateio", "gateio_futures"}
_GATE_PROVIDERS = {"gateio", "gateio_futures", "gateio_tradfi"}
_ARCHIVE_START = datetime(2023, 1, 1, tzinfo=timezone.utc)
_ARCHIVE_BASE_URL = "https://download.gatedata.org"
_SCHEMA_VERSION = 2
_NAMESPACE = "bronze/gate-history/v2"
_MANIFEST_NAMESPACE = "manifests/gate-history/v2"


@dataclass(frozen=True)
class GateHistoryRoute:
    canonical_symbol: str
    base_asset: str
    asset_class: str
    provider: str
    provider_symbol: str
    price_multiplier: str = "1"
    route_origin: str = "dynamic"

    @property
    def full_history_supported(self) -> bool:
        return self.provider in _FULL_HISTORY_PROVIDERS

    @property
    def archive_business(self) -> str | None:
        if self.provider == "gateio":
            return "spot"
        if self.provider == "gateio_futures":
            return "futures_usdt"
        return None


@dataclass(frozen=True)
class PartitionResult:
    timeframe: str
    year: int
    month: int
    rows: int
    object_key: str
    sha256: str
    first_timestamp: str | None
    last_timestamp: str | None
    missing_5m_inside_observed_span: int
    archive_days_found: int
    archive_days_missing: int
    rest_fallback_days: int
    reused: bool


def _utc_day_floor(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_datetime(value: str | None, default: datetime) -> datetime:
    if value is None:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _slug(value: str) -> str:
    return (
        value.strip()
        .replace("/", "-")
        .replace("_", "-")
        .replace(":", "-")
        .lower()
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _month_floor(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1, day=1)
    return value.replace(month=value.month + 1, day=1)


def iter_month_ranges(start: datetime, end: datetime) -> Iterable[tuple[datetime, datetime]]:
    if start >= end:
        return
    cursor = _month_floor(start)
    while cursor < end:
        month_end = _next_month(cursor)
        yield max(start, cursor), min(end, month_end)
        cursor = month_end


def iter_days(start: datetime, end: datetime) -> Iterable[datetime]:
    cursor = _utc_day_floor(start)
    while cursor < end:
        yield cursor
        cursor += timedelta(days=1)


def _load_static_universe() -> dict[str, tuple[str, str]]:
    path = Path("config/universe.json")
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    output: dict[str, tuple[str, str]] = {}
    for raw in payload.get("instruments", []):
        base = str(raw.get("base_asset") or "").upper()
        symbol = str(raw.get("symbol") or "").upper()
        asset_class = str(raw.get("asset_class") or "unknown").lower()
        if base and symbol and is_project_base_asset(base):
            output[base] = (symbol, asset_class)
    return output


def discover_gate_routes() -> list[GateHistoryRoute]:
    """Resolve every current project-universe asset with a Gate market route."""

    references = StormReferenceUniverseProvider().discover()
    if not references:
        raise ProviderError("Storm reference universe discovery returned no assets")

    static = _load_static_universe()
    canonical_by_base: dict[str, str] = {
        item.base_asset.upper(): item.canonical_symbol.upper() for item in references
    }
    asset_class_by_base: dict[str, str] = {
        item.base_asset.upper(): "storm" for item in references
    }
    for base, (symbol, asset_class) in static.items():
        canonical_by_base.setdefault(base, symbol)
        asset_class_by_base.setdefault(base, asset_class)

    registry = SourceMappingRegistry.load()
    for mapping in registry.all():
        if not is_project_base_asset(mapping.base_asset):
            continue
        canonical_by_base.setdefault(mapping.base_asset, f"{mapping.base_asset}/USDT")
        asset_class_by_base[mapping.base_asset] = mapping.asset_class

    gate_spot = GateIOSpotDiscoveryProvider().discover_instruments()
    spot_by_base: dict[str, list[object]] = {}
    for instrument in gate_spot:
        if not instrument.tradable:
            continue
        if instrument.quote_asset.upper() not in {"USDT", "USDC", "USD"}:
            continue
        spot_by_base.setdefault(instrument.base_asset.upper(), []).append(instrument)

    quote_rank = {"USDT": 0, "USDC": 1, "USD": 2}
    routes: list[GateHistoryRoute] = []
    seen: set[tuple[str, str, str]] = set()

    def add(route: GateHistoryRoute) -> None:
        key = (
            route.canonical_symbol.upper(),
            route.provider,
            route.provider_symbol.upper(),
        )
        if key not in seen:
            seen.add(key)
            routes.append(route)

    for base in sorted(canonical_by_base):
        canonical = canonical_by_base[base]
        asset_class = asset_class_by_base.get(base, "unknown")
        mapping = registry.get(base)
        explicit_spot = False
        if mapping is not None:
            for route in mapping.routes:
                if route.provider not in _GATE_PROVIDERS:
                    continue
                if route.provider == "gateio":
                    explicit_spot = True
                add(
                    GateHistoryRoute(
                        canonical_symbol=canonical,
                        base_asset=base,
                        asset_class=asset_class,
                        provider=route.provider,
                        provider_symbol=route.symbol.upper(),
                        price_multiplier=str(route.price_multiplier),
                        route_origin="source_registry",
                    )
                )

        if not explicit_spot:
            candidates = spot_by_base.get(base, [])
            if candidates:
                selected = min(
                    candidates,
                    key=lambda item: (
                        quote_rank.get(item.quote_asset.upper(), 99),
                        item.symbol,
                    ),
                )
                add(
                    GateHistoryRoute(
                        canonical_symbol=canonical,
                        base_asset=base,
                        asset_class=asset_class,
                        provider="gateio",
                        provider_symbol=selected.symbol.replace("/", "_").upper(),
                        route_origin="gate_spot_discovery",
                    )
                )

    return sorted(
        routes,
        key=lambda item: (
            item.canonical_symbol,
            item.provider,
            item.provider_symbol,
        ),
    )


def archive_url(route: GateHistoryRoute, day: datetime) -> str:
    business = route.archive_business
    if business is None:
        raise ValueError(f"no historical quotation archive for provider: {route.provider}")
    day = day.astimezone(timezone.utc)
    month = day.strftime("%Y%m")
    date = day.strftime("%Y%m%d")
    market = route.provider_symbol.replace("/", "_").upper()
    return (
        f"{_ARCHIVE_BASE_URL}/{business}/candlesticks_5m/{month}/"
        f"{market}-{date}.csv.gz"
    )


def _download_archive(url: str, destination: Path, timeout_seconds: int = 90) -> bool:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Trading-System-V3 gate-history-b2/2.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise ProviderError(f"Gate archive HTTP {response.status}: {url}")
            with destination.open("wb") as handle:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    handle.write(block)
        return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise ProviderError(f"Gate archive download failed HTTP {exc.code}: {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"Gate archive download failed: {url}") from exc


def _parse_archive_5m(
    path: Path,
    route: GateHistoryRoute,
    day: datetime,
) -> list[Candle]:
    multiplier = Decimal(route.price_multiplier)
    day_start = _utc_day_floor(day)
    day_end = day_start + timedelta(days=1)
    rows: dict[datetime, Candle] = {}
    try:
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            for line_number, raw in enumerate(reader, start=1):
                if not raw:
                    continue
                if len(raw) < 6:
                    raise ProviderError(
                        f"Gate historical quotation row {line_number} has fewer than 6 fields"
                    )
                try:
                    timestamp = datetime.fromtimestamp(
                        int(Decimal(raw[0])), tz=timezone.utc
                    )
                    volume = Decimal(raw[1])
                    close = Decimal(raw[2]) * multiplier
                    high = Decimal(raw[3]) * multiplier
                    low = Decimal(raw[4]) * multiplier
                    open_ = Decimal(raw[5]) * multiplier
                except (InvalidOperation, ValueError, OverflowError):
                    if line_number == 1:
                        continue
                    raise ProviderError(
                        f"Gate historical quotation row {line_number} is invalid"
                    )
                if timestamp < day_start or timestamp >= day_end:
                    continue
                if int(timestamp.timestamp()) % _SECONDS["5m"]:
                    raise ProviderError(
                        f"Gate archive 5m timestamp is not aligned: {timestamp.isoformat()}"
                    )
                candle = Candle(
                    symbol=route.canonical_symbol,
                    timeframe="5m",
                    timestamp=timestamp,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
                if timestamp in rows and rows[timestamp] != candle:
                    raise ProviderError(
                        f"conflicting duplicate Gate archive candle: {timestamp.isoformat()}"
                    )
                rows[timestamp] = candle
    except (OSError, EOFError) as exc:
        raise ProviderError(f"invalid Gate historical quotation gzip: {path}") from exc
    return [rows[key] for key in sorted(rows)]


def _fetch_recent_rest_5m(
    route: GateHistoryRoute,
    day: datetime,
) -> list[Candle]:
    start = _utc_day_floor(day)
    end = start + timedelta(days=1) - timedelta(minutes=5)
    multiplier = Decimal(route.price_multiplier)
    raw: list[Candle]
    if route.provider == "gateio":
        raw = GateIOProvider().get_candles_range(
            route.provider_symbol, "5m", start, end
        )
    elif route.provider == "gateio_futures":
        provider = GateIOFuturesProvider()
        contract = route.provider_symbol.replace("/", "_").upper()
        provider.rate_limiter.wait()
        url = (
            f"{provider.base_url}/futures/usdt/candlesticks"
            f"?contract={contract}&interval=5m"
            f"&from={int(start.timestamp())}&to={int(end.timestamp())}"
        )
        payload = provider.client.get_json(url)
        if not isinstance(payload, list):
            raise ProviderError(f"Gate.io futures candles invalid for {contract}")
        raw = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            raw.append(
                Candle(
                    symbol=route.provider_symbol,
                    timeframe="5m",
                    timestamp=datetime.fromtimestamp(float(row["t"]), tz=timezone.utc),
                    open=to_decimal(row["o"]),
                    high=to_decimal(row["h"]),
                    low=to_decimal(row["l"]),
                    close=to_decimal(row["c"]),
                    volume=to_decimal(row.get("sum", row.get("v", "0"))),
                )
            )
    else:
        return []

    normalized: dict[datetime, Candle] = {}
    for candle in raw:
        timestamp = candle.timestamp.astimezone(timezone.utc)
        if start <= timestamp < start + timedelta(days=1):
            normalized[timestamp] = Candle(
                symbol=route.canonical_symbol,
                timeframe="5m",
                timestamp=timestamp,
                open=candle.open * multiplier,
                high=candle.high * multiplier,
                low=candle.low * multiplier,
                close=candle.close * multiplier,
                volume=candle.volume,
            )
    return [normalized[key] for key in sorted(normalized)]


def fetch_month_5m(
    route: GateHistoryRoute,
    start: datetime,
    end: datetime,
) -> tuple[list[Candle], int, int, int]:
    output: dict[datetime, Candle] = {}
    archive_days_found = 0
    archive_days_missing = 0
    rest_fallback_days = 0
    recent_cutoff = _utc_day_floor(datetime.now(timezone.utc)) - timedelta(days=30)

    with tempfile.TemporaryDirectory(prefix="gate-archive-") as temp_dir:
        root = Path(temp_dir)
        for day in iter_days(start, end):
            path = root / f"{route.provider_symbol}-{day.strftime('%Y%m%d')}.csv.gz"
            found = _download_archive(archive_url(route, day), path)
            rows: list[Candle] = []
            if found:
                archive_days_found += 1
                rows = _parse_archive_5m(path, route, day)
            else:
                archive_days_missing += 1
                if day >= recent_cutoff:
                    try:
                        rows = _fetch_recent_rest_5m(route, day)
                    except ProviderError:
                        rows = []
                    if rows:
                        rest_fallback_days += 1
            for candle in rows:
                if start <= candle.timestamp < end:
                    output[candle.timestamp] = candle

    return (
        [output[key] for key in sorted(output)],
        archive_days_found,
        archive_days_missing,
        rest_fallback_days,
    )


def resample(candles: list[Candle], timeframe: str) -> list[Candle]:
    target = _SECONDS[timeframe]
    source = _SECONDS["5m"]
    expected_children = target // source
    buckets: dict[int, list[Candle]] = {}
    for candle in candles:
        stamp = int(candle.timestamp.timestamp())
        bucket = stamp - (stamp % target)
        buckets.setdefault(bucket, []).append(candle)

    output: list[Candle] = []
    for bucket_start in sorted(buckets):
        children = sorted(buckets[bucket_start], key=lambda item: item.timestamp)
        if len(children) != expected_children:
            continue
        expected = [bucket_start + source * index for index in range(expected_children)]
        actual = [int(item.timestamp.timestamp()) for item in children]
        if actual != expected:
            continue
        output.append(
            Candle(
                symbol=children[0].symbol,
                timeframe=timeframe,
                timestamp=datetime.fromtimestamp(bucket_start, tz=timezone.utc),
                open=children[0].open,
                high=max(item.high for item in children),
                low=min(item.low for item in children),
                close=children[-1].close,
                volume=sum((item.volume for item in children), Decimal("0")),
            )
        )
    return output


def _missing_inside_span(candles: list[Candle]) -> int:
    if not candles:
        return 0
    expected = (
        int((candles[-1].timestamp - candles[0].timestamp).total_seconds())
        // _SECONDS["5m"]
        + 1
    )
    return max(0, expected - len(candles))


def _write_parquet(
    path: Path,
    route: GateHistoryRoute,
    timeframe: str,
    candles: list[Candle],
) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "pyarrow is required; install the project research-data extra"
        ) from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    volume_semantics = "spot_archive_volume" if route.provider == "gateio" else "futures_size"
    table = pa.table(
        {
            "canonical_symbol": [route.canonical_symbol] * len(candles),
            "provider": [route.provider] * len(candles),
            "provider_symbol": [route.provider_symbol] * len(candles),
            "timeframe": [timeframe] * len(candles),
            "timestamp": [item.timestamp for item in candles],
            "open": [str(item.open) for item in candles],
            "high": [str(item.high) for item in candles],
            "low": [str(item.low) for item in candles],
            "close": [str(item.close) for item in candles],
            "volume": [str(item.volume) for item in candles],
            "volume_semantics": [volume_semantics] * len(candles),
            "price_multiplier": [route.price_multiplier] * len(candles),
            "source_timeframe": ["5m"] * len(candles),
            "source_kind": ["gate_historical_quotation"] * len(candles),
        }
    )
    pq.write_table(table, path, compression="zstd", version="2.6")


def _endpoint() -> str:
    value = os.environ.get("B2_S3_ENDPOINT", "").strip()
    if not value:
        raise RuntimeError("B2_S3_ENDPOINT is required")
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value.rstrip("/")


def _bucket() -> str:
    value = os.environ.get("B2_BUCKET_NAME", "").strip()
    if not value:
        raise RuntimeError("B2_BUCKET_NAME is required")
    return value


def _aws(*args: str, check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    command = ["aws", *args, "--endpoint-url", _endpoint()]
    return subprocess.run(
        command,
        check=check,
        text=True,
        stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
        stderr=subprocess.DEVNULL if quiet else subprocess.PIPE,
    )


def _object_missing(result: subprocess.CompletedProcess[str]) -> bool:
    """Only an explicit missing-object response permits an upload/rebuild."""
    if result.returncode == 0:
        return False
    match = re.search(r"An error occurred \(([^)]+)\)", result.stderr or "")
    code = match.group(1) if match else "unclassified"
    if code in {"404", "NoSuchKey", "NotFound"}:
        return True
    raise RuntimeError(
        f"B2 object lookup failed (rc={result.returncode}, code={code}); "
        "this is not a missing object. Run B2 Access Diagnostics; "
        "403 can also indicate an account download/transaction cap."
    )


def _object_exists(key: str) -> bool:
    result = _aws(
        "s3api",
        "head-object",
        "--bucket",
        _bucket(),
        "--key",
        key,
        check=False,
        quiet=False,
    )
    return not _object_missing(result)


def _put_file(path: Path, key: str, sha256: str, content_type: str) -> None:
    _aws(
        "s3api",
        "put-object",
        "--bucket",
        _bucket(),
        "--key",
        key,
        "--body",
        str(path),
        "--content-type",
        content_type,
        "--metadata",
        f"sha256={sha256}",
    )


def _put_json(payload: object, key: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, ensure_ascii=True)
        handle.write("\n")
        path = Path(handle.name)
    try:
        _put_file(path, key, _sha256(path), "application/json")
    finally:
        path.unlink(missing_ok=True)


def _partition_key(
    route: GateHistoryRoute,
    timeframe: str,
    start: datetime,
    end: datetime,
    run_end: datetime,
) -> str:
    base = (
        f"{_NAMESPACE}/provider={route.provider}/"
        f"canonical={_slug(route.canonical_symbol)}/"
        f"market={_slug(route.provider_symbol)}/timeframe={timeframe}/"
        f"year={start.year:04d}/month={start.month:02d}"
    )
    natural_end = _next_month(_month_floor(start))
    if end >= natural_end:
        return f"{base}/part-000.parquet"
    return f"{base}/snapshot={run_end.date().isoformat()}/part-000.parquet"


def _route_manifest_key(route: GateHistoryRoute) -> str:
    return (
        f"{_MANIFEST_NAMESPACE}/routes/provider={route.provider}/"
        f"canonical={_slug(route.canonical_symbol)}/"
        f"market={_slug(route.provider_symbol)}/manifest.json"
    )


def sync_route(
    route: GateHistoryRoute,
    *,
    start: datetime,
    end: datetime,
    force: bool = False,
) -> dict[str, object]:
    generated_at = datetime.now(timezone.utc)
    if not route.full_history_supported:
        manifest: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "status": "BLOCKED_FULL_HISTORY_UNAVAILABLE",
            "reason": (
                "Gate TradFi is represented in the universe, but this project has no verified "
                "complete historical quotation contract for that route."
            ),
            "route": asdict(route),
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "generated_at": generated_at.isoformat(),
            "partitions": [],
        }
        _put_json(manifest, _route_manifest_key(route))
        return manifest

    effective_start = max(start, _ARCHIVE_START)
    partitions: list[PartitionResult] = []
    observed_first: datetime | None = None
    observed_last: datetime | None = None
    total_5m_rows = 0
    total_missing_inside_span = 0
    total_archive_days_found = 0
    total_archive_days_missing = 0
    total_rest_fallback_days = 0

    for month_start, month_end in iter_month_ranges(effective_start, end):
        (
            five,
            archive_days_found,
            archive_days_missing,
            rest_fallback_days,
        ) = fetch_month_5m(route, month_start, month_end)
        if not five:
            continue

        missing_inside_span = _missing_inside_span(five)
        total_5m_rows += len(five)
        total_missing_inside_span += missing_inside_span
        total_archive_days_found += archive_days_found
        total_archive_days_missing += archive_days_missing
        total_rest_fallback_days += rest_fallback_days
        observed_first = min(observed_first or five[0].timestamp, five[0].timestamp)
        observed_last = max(observed_last or five[-1].timestamp, five[-1].timestamp)

        for timeframe in _TIMEFRAMES:
            rows = resample(five, timeframe)
            if not rows:
                continue
            key = _partition_key(route, timeframe, month_start, month_end, end)
            if _object_exists(key) and not force:
                partitions.append(
                    PartitionResult(
                        timeframe=timeframe,
                        year=month_start.year,
                        month=month_start.month,
                        rows=len(rows),
                        object_key=key,
                        sha256="EXISTING_OBJECT_NOT_REDOWNLOADED",
                        first_timestamp=rows[0].timestamp.isoformat(),
                        last_timestamp=rows[-1].timestamp.isoformat(),
                        missing_5m_inside_observed_span=missing_inside_span,
                        archive_days_found=archive_days_found,
                        archive_days_missing=archive_days_missing,
                        rest_fallback_days=rest_fallback_days,
                        reused=True,
                    )
                )
                continue

            with tempfile.TemporaryDirectory(prefix="gate-history-") as temp_dir:
                path = Path(temp_dir) / f"{timeframe}.parquet"
                _write_parquet(path, route, timeframe, rows)
                digest = _sha256(path)
                _put_file(path, key, digest, "application/vnd.apache.parquet")
            partitions.append(
                PartitionResult(
                    timeframe=timeframe,
                    year=month_start.year,
                    month=month_start.month,
                    rows=len(rows),
                    object_key=key,
                    sha256=digest,
                    first_timestamp=rows[0].timestamp.isoformat(),
                    last_timestamp=rows[-1].timestamp.isoformat(),
                    missing_5m_inside_observed_span=missing_inside_span,
                    archive_days_found=archive_days_found,
                    archive_days_missing=archive_days_missing,
                    rest_fallback_days=rest_fallback_days,
                    reused=False,
                )
            )

    status = "COMPLETE" if total_5m_rows > 0 else "NO_HISTORY_RETURNED"
    if status == "COMPLETE" and total_missing_inside_span > 0:
        status = "COMPLETE_WITH_RECORDED_GAPS"
    manifest = {
        "schema_version": _SCHEMA_VERSION,
        "status": status,
        "route": asdict(route),
        "requested_start": start.isoformat(),
        "effective_archive_start": effective_start.isoformat(),
        "requested_end": end.isoformat(),
        "generated_at": generated_at.isoformat(),
        "source_kind": "gate_historical_quotation",
        "source_timeframe": "5m",
        "derived_timeframes": list(_TIMEFRAMES),
        "observed_first": observed_first.isoformat() if observed_first else None,
        "observed_last": observed_last.isoformat() if observed_last else None,
        "total_5m_rows": total_5m_rows,
        "missing_5m_inside_observed_span": total_missing_inside_span,
        "archive_days_found": total_archive_days_found,
        "archive_days_missing": total_archive_days_missing,
        "rest_fallback_days": total_rest_fallback_days,
        "partitions": [asdict(item) for item in partitions],
    }
    _put_json(manifest, _route_manifest_key(route))
    return manifest


def _route_from_args(args: argparse.Namespace) -> GateHistoryRoute:
    if not all((args.canonical, args.base_asset, args.provider, args.provider_symbol)):
        raise ValueError(
            "route mode requires --canonical --base-asset --provider --provider-symbol"
        )
    return GateHistoryRoute(
        canonical_symbol=args.canonical.upper(),
        base_asset=args.base_asset.upper(),
        asset_class=args.asset_class,
        provider=args.provider,
        provider_symbol=args.provider_symbol.upper(),
        price_multiplier=args.price_multiplier,
        route_origin=args.route_origin,
    )


def _write_output(path: Path | None, payload: object) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover Gate-backed project-universe routes and sync the complete currently "
            "published Gate historical-quotation K-line archive to Backblaze B2."
        )
    )
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--canonical")
    parser.add_argument("--base-asset")
    parser.add_argument("--asset-class", default="unknown")
    parser.add_argument("--provider", choices=sorted(_GATE_PROVIDERS))
    parser.add_argument("--provider-symbol")
    parser.add_argument("--price-multiplier", default="1")
    parser.add_argument("--route-origin", default="workflow_matrix")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.discover_only:
        routes = discover_gate_routes()
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "archive_start": _ARCHIVE_START.isoformat(),
            "route_count": len(routes),
            "full_history_route_count": sum(item.full_history_supported for item in routes),
            "blocked_route_count": sum(not item.full_history_supported for item in routes),
            "routes": [asdict(item) for item in routes],
        }
        _write_output(args.output, payload)
        return 0 if routes else 2

    start = _parse_datetime(args.start, _ARCHIVE_START)
    end = _parse_datetime(args.end, _utc_day_floor(datetime.now(timezone.utc)))
    if start >= end:
        raise ValueError("start must be earlier than end")
    route = _route_from_args(args)
    try:
        manifest = sync_route(route, start=start, end=end, force=args.force)
    except Exception as exc:
        failure = {
            "schema_version": _SCHEMA_VERSION,
            "status": "ERROR",
            "route": asdict(route),
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partitions": [],
        }
        _write_output(args.output, failure)
        print("GATE_B2_ROUTE_SYNC_ERROR", file=sys.stderr)
        return 1
    _write_output(args.output, manifest)
    print("GATE_B2_ROUTE_SYNC_COMPLETE", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
