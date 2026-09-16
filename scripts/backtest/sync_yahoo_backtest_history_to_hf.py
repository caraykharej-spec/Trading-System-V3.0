"""Persist Yahoo fallback history with timeframe-specific lookback policies.

The legacy Yahoo writer used the 15-minute retention window for hourly data
as well. That is safe for transfer but too shallow for the project's 4h
backtest baseline. This writer keeps 15m inside Yahoo's short intraday window,
uses the materially longer hourly window for 1h/4h, and requests daily data
with explicit period1/period2 bounds to avoid long-range auto-downsampling.

Storage keys remain compatible with the v1 Yahoo namespace. Existing objects
are content-address verified before replacement, so reruns are idempotent.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.data.providers.http import ProviderError
from scripts.backtest import hf_s3
from scripts.backtest import sync_yahoo_history_to_hf as legacy

_FIFTEEN_MINUTE_DAYS = 59
_HOURLY_DAYS = 729
_DAILY_DAYS = 36_159  # 99 years, matching the conservative yfinance max policy.
_POLICY_VERSION = 2


def discover_routes() -> list[legacy.YahooRoute]:
    return legacy.discover_routes()


def sync_route(
    route: legacy.YahooRoute,
    *,
    end: datetime,
    force: bool = False,
) -> dict[str, object]:
    fifteen_start = end - timedelta(days=_FIFTEEN_MINUTE_DAYS)
    hourly_start = end - timedelta(days=_HOURLY_DAYS)
    daily_start = end - timedelta(days=_DAILY_DAYS)
    source_quality = {
        "15m": {"ohlc_invariant_rows_dropped": 0},
        "1h": {"ohlc_invariant_rows_dropped": 0},
        "1d": {"ohlc_invariant_rows_dropped": 0},
    }

    fifteen = legacy.fetch_history(
        route,
        "15m",
        start=fifteen_start,
        end=end,
        quality=source_quality["15m"],
    )
    hourly = legacy.fetch_history(
        route,
        "1h",
        start=hourly_start,
        end=end,
        quality=source_quality["1h"],
    )
    daily = legacy.fetch_history(
        route,
        "1d",
        start=daily_start,
        end=end,
        quality=source_quality["1d"],
    )

    datasets = {
        "15m": fifteen,
        "1h": hourly,
        "4h": legacy.aggregate_four_hour(hourly),
        "1d": daily,
    }
    if any(not rows for rows in datasets.values()):
        missing = [timeframe for timeframe, rows in datasets.items() if not rows]
        raise ProviderError(f"Yahoo returned no history for: {','.join(missing)}")

    partitions: list[legacy.YahooPartition] = []
    coverage: dict[str, object] = {}
    for timeframe, rows in datasets.items():
        coverage[timeframe] = {
            "rows": len(rows),
            "first_timestamp": rows[0].timestamp.isoformat(),
            "last_timestamp": rows[-1].timestamp.isoformat(),
            "source_ohlc_invariant_rows_dropped": (
                source_quality.get(timeframe, {}).get("ohlc_invariant_rows_dropped", 0)
            ),
        }
        for year, year_rows in legacy._year_groups(rows):
            partitions.append(
                legacy._store_partition(route, timeframe, year, year_rows, force=force)
            )

    manifest: dict[str, object] = {
        "schema_version": _POLICY_VERSION,
        "status": "COMPLETE",
        "route": asdict(route),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_end": end.isoformat(),
        "source_kind": "yahoo_public_chart_api_personal_research",
        "usage_policy": "private_personal_research_not_public_redistribution",
        "history_policy": {
            "15m": f"last_{_FIFTEEN_MINUTE_DAYS}_days",
            "1h": f"last_{_HOURLY_DAYS}_days",
            "4h": f"derived_from_last_{_HOURLY_DAYS}_days_of_1h",
            "1d": f"explicit_last_{_DAILY_DAYS}_days",
        },
        "price_policy": "raw_ohlc_plus_separate_adjusted_close",
        "gap_policy": "preserve_source_market_sessions_no_fill",
        "invalid_source_row_policy": "drop_and_record_never_clamp",
        "source_ohlc_invariant_rows_dropped": sum(
            item["ohlc_invariant_rows_dropped"] for item in source_quality.values()
        ),
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
        f"{legacy._MANIFEST_NAMESPACE}/routes/canonical={legacy._slug(route.canonical_symbol)}/"
        f"market={legacy._slug(route.provider_symbol)}.json"
    )
    legacy._put_json(manifest, manifest_key)
    manifest["manifest_object_key"] = manifest_key
    return manifest


def _route_from_args(args: argparse.Namespace) -> legacy.YahooRoute:
    return legacy.YahooRoute(
        canonical_symbol=args.canonical,
        base_asset=args.base_asset,
        asset_class=args.asset_class,
        provider_symbol=args.provider_symbol,
        price_multiplier=args.price_multiplier,
        requires_volume=args.requires_volume,
    )


def main() -> int:
    # Install the shared HF transport so every object request, not just the
    # matrix job, observes the five-minute-aware throttling policy.
    legacy._aws = hf_s3.aws

    parser = argparse.ArgumentParser(
        description="Backfill backtest-ready Yahoo routes to private HF storage"
    )
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--canonical")
    parser.add_argument("--base-asset")
    parser.add_argument("--asset-class", default="unknown")
    parser.add_argument("--provider-symbol")
    parser.add_argument("--price-multiplier", default="1")
    parser.add_argument(
        "--requires-volume", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--end")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.discover_only:
        routes = discover_routes()
        payload = {
            "schema_version": _POLICY_VERSION,
            "route_count": len(routes),
            "routes": [asdict(route) for route in routes],
        }
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
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
            "schema_version": _POLICY_VERSION,
            "status": "ERROR",
            "route": asdict(route),
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
