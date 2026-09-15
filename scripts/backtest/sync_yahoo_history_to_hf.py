"""Persist every explicit Yahoo fallback route in the private HF research bucket."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from app.data.providers.http import ProviderError
from app.data.source_registry import SourceMappingRegistry

_API_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_NAMESPACE = "bronze/yahoo-history/v1"
_MANIFEST_NAMESPACE = "manifests/yahoo-history/v1"
_SCHEMA_VERSION = 1
_INTRADAY_DAYS = 59


@dataclass(frozen=True)
class YahooRoute:
    canonical_symbol: str
    base_asset: str
    asset_class: str
    provider_symbol: str
    price_multiplier: str = "1"
    requires_volume: bool = True


@dataclass(frozen=True)
class YahooCandle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal | None
    volume: Decimal | None


@dataclass(frozen=True)
class YahooPartition:
    timeframe: str
    year: int
    rows: int
    object_key: str
    sha256: str
    first_timestamp: str
    last_timestamp: str
    reused_verified: bool


def discover_routes() -> list[YahooRoute]:
    routes: list[YahooRoute] = []
    seen: set[tuple[str, str]] = set()
    for mapping in SourceMappingRegistry.load().all():
        for route in mapping.routes:
            if route.provider != "yahoo":
                continue
            key = (mapping.base_asset, route.symbol.upper())
            if key in seen:
                continue
            seen.add(key)
            routes.append(
                YahooRoute(
                    canonical_symbol=mapping.base_asset,
                    base_asset=mapping.base_asset,
                    asset_class=mapping.asset_class,
                    provider_symbol=route.symbol,
                    price_multiplier=str(route.price_multiplier),
                    requires_volume=route.requires_volume,
                )
            )
    return sorted(routes, key=lambda item: (item.canonical_symbol, item.provider_symbol))


def _request_json(url: str, *, attempts: int = 7) -> object:
    delay = 2.0
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Trading-System-V3 yahoo-history-research/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise ProviderError(f"Yahoo HTTP {response.status}")
                return json.load(response)
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {408, 429} or 500 <= exc.code < 600
            if not retryable or attempt == attempts:
                raise ProviderError(f"Yahoo HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            if attempt == attempts:
                raise ProviderError("Yahoo request or response failure") from exc
        time.sleep(delay)
        delay = min(delay * 2, 30.0)
    raise AssertionError("unreachable")


def _chart_url(symbol: str, interval: str, start: datetime, end: datetime) -> str:
    query = urllib.parse.urlencode(
        {
            "period1": int(start.timestamp()),
            "period2": int(end.timestamp()),
            "interval": interval,
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
    )
    return f"{_API_BASE}/{urllib.parse.quote(symbol, safe='')}?{query}"


def _max_chart_url(symbol: str, interval: str) -> str:
    query = urllib.parse.urlencode(
        {
            "range": "max",
            "interval": interval,
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
    )
    return f"{_API_BASE}/{urllib.parse.quote(symbol, safe='')}?{query}"


def parse_chart(payload: object, route: YahooRoute) -> list[YahooCandle]:
    if not isinstance(payload, dict):
        raise ProviderError("Yahoo chart response is not an object")
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise ProviderError("Yahoo chart envelope is missing")
    if chart.get("error"):
        raise ProviderError(f"Yahoo chart error: {chart['error']}")
    results = chart.get("result") or []
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ProviderError(f"Yahoo chart not found: {route.provider_symbol}")
    data = results[0]
    timestamps = data.get("timestamp") or []
    indicators = data.get("indicators") or {}
    quotes = indicators.get("quote") or [] if isinstance(indicators, dict) else []
    adjusted = indicators.get("adjclose") or [] if isinstance(indicators, dict) else []
    if not quotes or not isinstance(quotes[0], dict):
        raise ProviderError(f"Yahoo quote data missing: {route.provider_symbol}")
    quote = quotes[0]
    adjusted_values = (
        adjusted[0].get("adjclose", []) if adjusted and isinstance(adjusted[0], dict) else []
    )
    multiplier = Decimal(route.price_multiplier)
    rows: dict[datetime, YahooCandle] = {}
    for index, raw_timestamp in enumerate(timestamps):
        try:
            values = [quote.get(name, [])[index] for name in ("open", "high", "low", "close")]
        except (IndexError, TypeError):
            continue
        if any(value is None for value in values):
            continue
        try:
            timestamp = datetime.fromtimestamp(float(raw_timestamp), tz=timezone.utc)
            open_, high, low, close = (Decimal(str(value)) * multiplier for value in values)
            raw_adjusted = adjusted_values[index] if index < len(adjusted_values) else None
            adjusted_close = (
                Decimal(str(raw_adjusted)) * multiplier if raw_adjusted is not None else None
            )
            volumes = quote.get("volume") or []
            raw_volume = volumes[index] if index < len(volumes) else None
            volume = Decimal(str(raw_volume)) if raw_volume is not None else None
        except (InvalidOperation, OverflowError, TypeError, ValueError) as exc:
            raise ProviderError("Yahoo chart contains an invalid numeric value") from exc
        if low > high or open_ < low or open_ > high or close < low or close > high:
            raise ProviderError(f"Yahoo OHLC invariant violation at {timestamp.isoformat()}")
        candle = YahooCandle(timestamp, open_, high, low, close, adjusted_close, volume)
        prior = rows.get(timestamp)
        if prior is not None and prior != candle:
            raise ProviderError(f"Yahoo conflicting duplicate at {timestamp.isoformat()}")
        rows[timestamp] = candle
    return [rows[key] for key in sorted(rows)]


def fetch_history(
    route: YahooRoute, interval: str, *, start: datetime, end: datetime
) -> list[YahooCandle]:
    payload = _request_json(_chart_url(route.provider_symbol, interval, start, end))
    return parse_chart(payload, route)


def fetch_max_history(route: YahooRoute, interval: str) -> list[YahooCandle]:
    payload = _request_json(_max_chart_url(route.provider_symbol, interval))
    return parse_chart(payload, route)


def aggregate_four_hour(rows: list[YahooCandle]) -> list[YahooCandle]:
    buckets: dict[int, list[YahooCandle]] = {}
    for row in rows:
        epoch = int(row.timestamp.timestamp())
        buckets.setdefault(epoch - epoch % 14_400, []).append(row)
    output: list[YahooCandle] = []
    for epoch, group in sorted(buckets.items()):
        ordered = sorted(group, key=lambda item: item.timestamp)
        adjusted = ordered[-1].adjusted_close
        volumes = [item.volume for item in ordered]
        volume = sum((item for item in volumes if item is not None), Decimal("0"))
        output.append(
            YahooCandle(
                timestamp=datetime.fromtimestamp(epoch, tz=timezone.utc),
                open=ordered[0].open,
                high=max(item.high for item in ordered),
                low=min(item.low for item in ordered),
                close=ordered[-1].close,
                adjusted_close=adjusted,
                volume=volume if any(item is not None for item in volumes) else None,
            )
        )
    return output


def _year_groups(rows: list[YahooCandle]) -> Iterable[tuple[int, list[YahooCandle]]]:
    groups: dict[int, list[YahooCandle]] = {}
    for row in rows:
        groups.setdefault(row.timestamp.year, []).append(row)
    for year in sorted(groups):
        yield year, sorted(groups[year], key=lambda item: item.timestamp)


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("_") or "unknown"


def _endpoint() -> str:
    value = os.environ.get("HF_S3_ENDPOINT", "").strip().rstrip("/")
    if not value:
        raise RuntimeError("HF_S3_ENDPOINT is required")
    return value if value.startswith("https://") else "https://" + value


def _bucket() -> str:
    value = os.environ.get("HF_S3_BUCKET", "").strip()
    if not value:
        raise RuntimeError("HF_S3_BUCKET is required")
    return value


def _aws(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["aws", *args, "--endpoint-url", _endpoint()],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _missing(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        return False
    match = re.search(r"An error occurred \(([^)]+)\)", result.stderr or "")
    code = match.group(1) if match else "unclassified"
    if code in {"404", "NoSuchKey", "NotFound"}:
        return True
    raise RuntimeError(f"HF object lookup failed (rc={result.returncode}, code={code})")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _remote_sha256(key: str) -> str | None:
    with tempfile.TemporaryDirectory(prefix="hf-yahoo-verify-") as temp_dir:
        target = Path(temp_dir) / "object.bin"
        result = _aws(
            "s3api", "get-object", "--bucket", _bucket(), "--key", key, str(target), check=False
        )
        if _missing(result):
            return None
        if not target.is_file():
            raise RuntimeError("HF read-back succeeded without producing an object file")
        return _sha256(target)


def _put_verified(path: Path, key: str, digest: str, content_type: str) -> None:
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
    )
    if _remote_sha256(key) != digest:
        raise RuntimeError(f"HF SHA-256 read-back verification failed for {key}")


def _write_parquet(path: Path, route: YahooRoute, timeframe: str, rows: list[YahooCandle]) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required; install the research-data extra") from exc
    table = pa.table(
        {
            "canonical_symbol": [route.canonical_symbol] * len(rows),
            "provider": ["yahoo"] * len(rows),
            "provider_symbol": [route.provider_symbol] * len(rows),
            "asset_class": [route.asset_class] * len(rows),
            "timeframe": [timeframe] * len(rows),
            "timestamp": [item.timestamp for item in rows],
            "open": [str(item.open) for item in rows],
            "high": [str(item.high) for item in rows],
            "low": [str(item.low) for item in rows],
            "close": [str(item.close) for item in rows],
            "adjusted_close": [
                str(item.adjusted_close) if item.adjusted_close is not None else None
                for item in rows
            ],
            "volume": [str(item.volume) if item.volume is not None else None for item in rows],
            "price_multiplier": [route.price_multiplier] * len(rows),
            "source_kind": ["yahoo_public_chart_api_personal_research"] * len(rows),
        }
    )
    pq.write_table(table, path, compression="zstd", version="2.6")


def _partition_key(route: YahooRoute, timeframe: str, year: int) -> str:
    return (
        f"{_NAMESPACE}/canonical={_slug(route.canonical_symbol)}/"
        f"market={_slug(route.provider_symbol)}/timeframe={timeframe}/"
        f"year={year:04d}/part-000.parquet"
    )


def _store_partition(
    route: YahooRoute,
    timeframe: str,
    year: int,
    rows: list[YahooCandle],
    *,
    force: bool,
) -> YahooPartition:
    key = _partition_key(route, timeframe, year)
    with tempfile.TemporaryDirectory(prefix="yahoo-history-") as temp_dir:
        path = Path(temp_dir) / "part-000.parquet"
        _write_parquet(path, route, timeframe, rows)
        digest = _sha256(path)
        existing = _remote_sha256(key)
        reused = existing == digest and not force
        if not reused:
            _put_verified(path, key, digest, "application/vnd.apache.parquet")
    return YahooPartition(
        timeframe=timeframe,
        year=year,
        rows=len(rows),
        object_key=key,
        sha256=digest,
        first_timestamp=rows[0].timestamp.isoformat(),
        last_timestamp=rows[-1].timestamp.isoformat(),
        reused_verified=reused,
    )


def _put_json(payload: object, key: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, ensure_ascii=True)
        handle.write("\n")
        path = Path(handle.name)
    try:
        _put_verified(path, key, _sha256(path), "application/json")
    finally:
        path.unlink(missing_ok=True)


def sync_route(route: YahooRoute, *, end: datetime, force: bool = False) -> dict[str, object]:
    intraday_start = end - timedelta(days=_INTRADAY_DAYS)
    fifteen = fetch_history(route, "15m", start=intraday_start, end=end)
    hourly = fetch_history(route, "1h", start=intraday_start, end=end)
    daily = fetch_max_history(route, "1d")
    datasets = {"15m": fifteen, "1h": hourly, "4h": aggregate_four_hour(hourly), "1d": daily}
    if any(not rows for rows in datasets.values()):
        missing = [timeframe for timeframe, rows in datasets.items() if not rows]
        raise ProviderError(f"Yahoo returned no history for: {','.join(missing)}")
    partitions: list[YahooPartition] = []
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
        "route": asdict(route),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_end": end.isoformat(),
        "source_kind": "yahoo_public_chart_api_personal_research",
        "usage_policy": "private_personal_research_not_public_redistribution",
        "intraday_history_policy": f"last_{_INTRADAY_DAYS}_days",
        "daily_history_policy": "maximum_available_range",
        "price_policy": "raw_ohlc_plus_separate_adjusted_close",
        "gap_policy": "preserve_source_market_sessions_no_fill",
        "integrity_policy": "sha256_manifest_compare_upload_verify_downloaded_bytes",
        "coverage": coverage,
        "total_rows": sum(len(rows) for rows in datasets.values()),
        "partition_objects_recorded": len(partitions),
        "reused_verified_partition_objects": sum(item.reused_verified for item in partitions),
        "uploaded_or_replaced_partition_objects": sum(
            not item.reused_verified for item in partitions
        ),
        "partitions": [asdict(item) for item in partitions],
    }
    manifest_key = (
        f"{_MANIFEST_NAMESPACE}/routes/canonical={_slug(route.canonical_symbol)}/"
        f"market={_slug(route.provider_symbol)}.json"
    )
    _put_json(manifest, manifest_key)
    manifest["manifest_object_key"] = manifest_key
    return manifest


def _route_from_args(args: argparse.Namespace) -> YahooRoute:
    return YahooRoute(
        canonical_symbol=args.canonical,
        base_asset=args.base_asset,
        asset_class=args.asset_class,
        provider_symbol=args.provider_symbol,
        price_multiplier=args.price_multiplier,
        requires_volume=args.requires_volume,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill explicit Yahoo routes to private HF")
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--canonical")
    parser.add_argument("--base-asset")
    parser.add_argument("--asset-class", default="unknown")
    parser.add_argument("--provider-symbol")
    parser.add_argument("--price-multiplier", default="1")
    parser.add_argument("--requires-volume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--end")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.discover_only:
        routes = discover_routes()
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "route_count": len(routes),
            "routes": [asdict(route) for route in routes],
        }
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    if not args.canonical or not args.base_asset or not args.provider_symbol:
        raise SystemExit("route mode requires --canonical --base-asset --provider-symbol")
    end = (
        datetime.fromisoformat(args.end.replace("Z", "+00:00"))
        if args.end
        else datetime.now(timezone.utc)
    )
    if end.tzinfo is None:
        raise SystemExit("--end must include a timezone")
    route = _route_from_args(args)
    try:
        payload = sync_route(route, end=end.astimezone(timezone.utc), force=args.force)
    except Exception as exc:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "status": "ERROR",
            "route": asdict(route),
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
