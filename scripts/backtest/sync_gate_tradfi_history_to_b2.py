from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from app.data.market_data import Candle
from app.data.providers.http import ProviderError
from scripts.backtest.sync_gate_universe_history_to_b2 import (
    GateHistoryRoute,
    _aws,
    _bucket,
    _put_file,
    _put_json,
    _route_manifest_key,
    _sha256,
    _slug,
    discover_gate_routes,
)

_API_BASE = "https://api.gateio.ws/api/v4"
_TIMEFRAMES = ("15m", "1h", "4h", "1d")
_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
_SCHEMA_VERSION = 3
_NAMESPACE = "bronze/gate-history/v2"
_MANIFEST_NAMESPACE = "manifests/gate-history/v2"
_PAGE_LIMIT = 500
_MAX_PAGES = 5000


@dataclass(frozen=True)
class TradFiPartition:
    timeframe: str
    year: int
    month: int
    rows: int
    object_key: str
    sha256: str
    first_timestamp: str
    last_timestamp: str
    reused_verified: bool


def _month_groups(candles: list[Candle]) -> Iterable[tuple[tuple[int, int], list[Candle]]]:
    groups: dict[tuple[int, int], list[Candle]] = {}
    for candle in candles:
        key = (candle.timestamp.year, candle.timestamp.month)
        groups.setdefault(key, []).append(candle)
    for key in sorted(groups):
        yield key, sorted(groups[key], key=lambda item: item.timestamp)


def _extract_rows(payload: object) -> list[dict[str, object]]:
    current = payload
    if isinstance(current, dict) and "data" in current:
        current = current["data"]
    if isinstance(current, dict):
        for key in ("list", "items", "klines", "data"):
            value = current.get(key)
            if isinstance(value, list):
                current = value
                break
    if not isinstance(current, list):
        raise ProviderError("Gate TradFi K-line response does not contain a list")
    output: list[dict[str, object]] = []
    for item in current:
        if isinstance(item, dict):
            output.append(item)
    return output


def _parse_kline_rows(
    payload: object,
    route: GateHistoryRoute,
    timeframe: str,
) -> list[Candle]:
    multiplier = Decimal(route.price_multiplier)
    interval = _SECONDS[timeframe]
    output: dict[datetime, Candle] = {}
    for raw in _extract_rows(payload):
        try:
            stamp = int(raw["t"])
            timestamp = datetime.fromtimestamp(stamp, tz=timezone.utc)
            open_ = Decimal(str(raw["o"])) * multiplier
            close = Decimal(str(raw["c"])) * multiplier
            high = Decimal(str(raw["h"])) * multiplier
            low = Decimal(str(raw["l"])) * multiplier
        except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as exc:
            raise ProviderError(f"invalid Gate TradFi {timeframe} K-line row: {raw!r}") from exc
        if stamp % interval:
            raise ProviderError(
                f"Gate TradFi {timeframe} timestamp is not aligned: {timestamp.isoformat()}"
            )
        if low > high or open_ < low or open_ > high or close < low or close > high:
            raise ProviderError(
                f"Gate TradFi OHLC invariant violation at {timestamp.isoformat()}"
            )
        candle = Candle(
            symbol=route.canonical_symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=Decimal("0"),
        )
        prior = output.get(timestamp)
        if prior is not None and prior != candle:
            raise ProviderError(
                f"conflicting duplicate Gate TradFi candle at {timestamp.isoformat()}"
            )
        output[timestamp] = candle
    return [output[key] for key in sorted(output)]


def _request_json(url: str, *, attempts: int = 7) -> object:
    delay = 1.0
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Trading-System-V3 gate-tradfi-history-b2/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise ProviderError(f"Gate TradFi HTTP {response.status}: {url}")
                return json.load(response)
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt == attempts:
                body = exc.read().decode("utf-8", errors="replace")[:1000]
                raise ProviderError(
                    f"Gate TradFi HTTP {exc.code}: {url}; body={body}"
                ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == attempts:
                raise ProviderError(f"Gate TradFi request failed: {url}") from exc
        time.sleep(delay)
        delay = min(delay * 2, 20.0)
    raise AssertionError("unreachable")


def _page_url(symbol: str, timeframe: str, end_time: int) -> str:
    query = urllib.parse.urlencode(
        {
            "kline_type": timeframe,
            "end_time": end_time,
            "limit": _PAGE_LIMIT,
        }
    )
    encoded = urllib.parse.quote(symbol, safe="")
    return f"{_API_BASE}/tradfi/symbols/{encoded}/klines?{query}"


def fetch_all_history(
    route: GateHistoryRoute,
    timeframe: str,
    *,
    end: datetime,
    max_pages: int = _MAX_PAGES,
) -> tuple[list[Candle], int]:
    cursor = int(end.astimezone(timezone.utc).timestamp()) - 1
    rows: dict[datetime, Candle] = {}
    page_count = 0
    request_delay = max(0.0, float(os.environ.get("GATE_TRADFI_REQUEST_DELAY", "1.0")))

    while page_count < max_pages:
        payload = _request_json(_page_url(route.provider_symbol, timeframe, cursor))
        page = _parse_kline_rows(payload, route, timeframe)
        page = [item for item in page if int(item.timestamp.timestamp()) <= cursor]
        page_count += 1
        if not page:
            break

        for candle in page:
            prior = rows.get(candle.timestamp)
            if prior is not None and prior != candle:
                raise ProviderError(
                    f"conflicting duplicate Gate TradFi candle at {candle.timestamp.isoformat()}"
                )
            rows[candle.timestamp] = candle

        earliest = min(int(item.timestamp.timestamp()) for item in page)
        next_cursor = earliest - 1
        if next_cursor >= cursor:
            raise ProviderError(
                f"Gate TradFi pagination did not move backward for {route.provider_symbol} {timeframe}"
            )
        cursor = next_cursor
        if request_delay:
            time.sleep(request_delay)

    if page_count >= max_pages:
        raise ProviderError(
            f"Gate TradFi pagination exceeded {max_pages} pages for "
            f"{route.provider_symbol} {timeframe}"
        )
    return [rows[key] for key in sorted(rows)], page_count


def _partition_key(route: GateHistoryRoute, timeframe: str, year: int, month: int) -> str:
    return (
        f"{_NAMESPACE}/provider=gateio_tradfi/"
        f"canonical={_slug(route.canonical_symbol)}/"
        f"market={_slug(route.provider_symbol)}/timeframe={timeframe}/"
        f"year={year:04d}/month={month:02d}/part-000.parquet"
    )


def _head_sha256(key: str) -> str | None:
    result = _aws(
        "s3api",
        "head-object",
        "--bucket",
        _bucket(),
        "--key",
        key,
        "--output",
        "json",
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    metadata = payload.get("Metadata") or payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("sha256") or metadata.get("Sha256")
    return str(value) if value else None


def _write_parquet(path: Path, route: GateHistoryRoute, timeframe: str, candles: list[Candle]) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required; install the research-data extra") from exc

    table = pa.table(
        {
            "canonical_symbol": [route.canonical_symbol] * len(candles),
            "provider": ["gateio_tradfi"] * len(candles),
            "provider_symbol": [route.provider_symbol] * len(candles),
            "timeframe": [timeframe] * len(candles),
            "timestamp": [item.timestamp for item in candles],
            "open": [str(item.open) for item in candles],
            "high": [str(item.high) for item in candles],
            "low": [str(item.low) for item in candles],
            "close": [str(item.close) for item in candles],
            "volume": [None] * len(candles),
            "volume_semantics": ["not_provided_by_gate_tradfi_kline"] * len(candles),
            "price_multiplier": [route.price_multiplier] * len(candles),
            "source_timeframe": [timeframe] * len(candles),
            "source_kind": ["gate_tradfi_public_kline_rest"] * len(candles),
        }
    )
    pq.write_table(table, path, compression="zstd", version="2.6")


def _store_partition(
    route: GateHistoryRoute,
    timeframe: str,
    year: int,
    month: int,
    candles: list[Candle],
    *,
    force: bool,
) -> TradFiPartition:
    import tempfile

    key = _partition_key(route, timeframe, year, month)
    with tempfile.TemporaryDirectory(prefix="gate-tradfi-") as temp_dir:
        path = Path(temp_dir) / "part-000.parquet"
        _write_parquet(path, route, timeframe, candles)
        digest = _sha256(path)
        existing = _head_sha256(key)
        reused = existing == digest and not force
        if not reused:
            _put_file(path, key, digest, "application/vnd.apache.parquet")
            verified = _head_sha256(key)
            if verified != digest:
                raise RuntimeError(
                    f"B2 SHA-256 metadata verification failed for {key}: {verified!r} != {digest!r}"
                )
    return TradFiPartition(
        timeframe=timeframe,
        year=year,
        month=month,
        rows=len(candles),
        object_key=key,
        sha256=digest,
        first_timestamp=candles[0].timestamp.isoformat(),
        last_timestamp=candles[-1].timestamp.isoformat(),
        reused_verified=reused,
    )


def sync_route(route: GateHistoryRoute, *, end: datetime, force: bool = False) -> dict[str, object]:
    if route.provider != "gateio_tradfi":
        raise ValueError(f"expected gateio_tradfi route, got {route.provider}")

    generated_at = datetime.now(timezone.utc)
    partitions: list[TradFiPartition] = []
    coverage: dict[str, dict[str, object]] = {}
    total_rows = 0

    for timeframe in _TIMEFRAMES:
        candles, pages = fetch_all_history(route, timeframe, end=end)
        if not candles:
            raise ProviderError(
                f"Gate TradFi returned no {timeframe} history for {route.provider_symbol}"
            )
        coverage[timeframe] = {
            "rows": len(candles),
            "pages": pages,
            "first_timestamp": candles[0].timestamp.isoformat(),
            "last_timestamp": candles[-1].timestamp.isoformat(),
        }
        total_rows += len(candles)
        for (year, month), month_rows in _month_groups(candles):
            partitions.append(
                _store_partition(
                    route,
                    timeframe,
                    year,
                    month,
                    month_rows,
                    force=force,
                )
            )

    observed_first = min(
        str(item["first_timestamp"]) for item in coverage.values()
    )
    observed_last = max(
        str(item["last_timestamp"]) for item in coverage.values()
    )
    manifest: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "COMPLETE",
        "route": asdict(route),
        "generated_at": generated_at.isoformat(),
        "requested_end": end.isoformat(),
        "source_kind": "gate_tradfi_public_kline_rest",
        "source_endpoint": "/api/v4/tradfi/symbols/{symbol}/klines",
        "source_authorization": "none",
        "pagination": "backward_by_end_time_limit_500_until_empty",
        "native_timeframes": list(_TIMEFRAMES),
        "gap_policy": "preserve_source_native_market_sessions_no_fill",
        "volume_policy": "not_provided_by_gate_tradfi_kline",
        "integrity_policy": "sha256_rebuild_compare_upload_verify_metadata",
        "observed_first": observed_first,
        "observed_last": observed_last,
        "total_rows": total_rows,
        "coverage": coverage,
        "partition_objects_recorded": len(partitions),
        "reused_verified_partition_objects": sum(item.reused_verified for item in partitions),
        "uploaded_or_replaced_partition_objects": sum(not item.reused_verified for item in partitions),
        "partitions": [asdict(item) for item in partitions],
    }
    _put_json(manifest, _route_manifest_key(route))
    return manifest


def _discover() -> list[GateHistoryRoute]:
    return [route for route in discover_gate_routes() if route.provider == "gateio_tradfi"]


def _route_from_args(args: argparse.Namespace) -> GateHistoryRoute:
    return GateHistoryRoute(
        canonical_symbol=args.canonical,
        base_asset=args.base_asset,
        asset_class=args.asset_class,
        provider="gateio_tradfi",
        provider_symbol=args.provider_symbol,
        price_multiplier=args.price_multiplier,
        route_origin=args.route_origin,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Gate TradFi public K-lines to B2")
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--publish-manifest")
    parser.add_argument("--run-id")
    parser.add_argument("--canonical")
    parser.add_argument("--base-asset")
    parser.add_argument("--asset-class", default="unknown")
    parser.add_argument("--provider-symbol")
    parser.add_argument("--price-multiplier", default="1")
    parser.add_argument("--route-origin", default="source_registry")
    parser.add_argument("--end")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.discover_only:
        routes = _discover()
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "route_count": len(routes),
            "routes": [asdict(item) for item in routes],
        }
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0

    if args.publish_manifest:
        if not args.run_id:
            raise SystemExit("--run-id is required with --publish-manifest")
        payload = json.loads(Path(args.publish_manifest).read_text(encoding="utf-8"))
        key = f"{_MANIFEST_NAMESPACE}/runs/{args.run_id}-tradfi.json"
        _put_json(payload, key)
        output.write_text(json.dumps({"object_key": key}, indent=2) + "\n", encoding="utf-8")
        return 0

    required = (args.canonical, args.base_asset, args.provider_symbol)
    if any(value is None for value in required):
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
