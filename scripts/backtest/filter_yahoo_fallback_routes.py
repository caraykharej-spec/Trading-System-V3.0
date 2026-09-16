"""Filter Yahoo history discovery to the canonical historical fallback route per asset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.data.source_registry import SourceMappingRegistry

_FULL_HISTORY_GATE_PROVIDERS = {"gateio", "gateio_futures"}


def filter_fallback_routes(payload: dict[str, object]) -> dict[str, object]:
    raw_routes = payload.get("routes")
    if not isinstance(raw_routes, list):
        raise ValueError("Yahoo discovery payload must contain a routes list")

    registry = SourceMappingRegistry.load()
    selected: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []

    for raw in raw_routes:
        if not isinstance(raw, dict):
            raise ValueError("Yahoo discovery route must be an object")
        base = str(raw.get("base_asset") or "").strip().upper()
        provider_symbol = str(raw.get("provider_symbol") or "").strip()
        if not base:
            raise ValueError("Yahoo discovery route is missing base_asset")
        if not provider_symbol:
            raise ValueError("Yahoo discovery route is missing provider_symbol")

        mapping = registry.get(base)
        if mapping is None:
            raise ValueError(f"Yahoo route has no source-registry mapping: {base}")

        explicit_full_gate = [
            route.provider
            for route in mapping.routes
            if route.provider in _FULL_HISTORY_GATE_PROVIDERS
        ]
        if explicit_full_gate:
            excluded.append(
                {
                    "base_asset": base,
                    "provider_symbol": provider_symbol,
                    "reason": "explicit_full_history_gate_route_available",
                    "gate_providers": sorted(set(explicit_full_gate)),
                }
            )
            continue

        primary_yahoo = next(
            (route for route in mapping.routes if route.provider == "yahoo"),
            None,
        )
        if primary_yahoo is None:
            raise ValueError(f"Yahoo discovery route has no Yahoo registry route: {base}")
        if provider_symbol != primary_yahoo.symbol:
            excluded.append(
                {
                    "base_asset": base,
                    "provider_symbol": provider_symbol,
                    "reason": "secondary_yahoo_route_not_selected_for_historical_archive",
                    "primary_yahoo_symbol": primary_yahoo.symbol,
                }
            )
            continue

        selected.append(raw)

    full_gate_excluded = sum(
        item["reason"] == "explicit_full_history_gate_route_available" for item in excluded
    )
    secondary_yahoo_excluded = sum(
        item["reason"] == "secondary_yahoo_route_not_selected_for_historical_archive"
        for item in excluded
    )
    return {
        "schema_version": 2,
        "selection_policy": (
            "primary_explicit_yahoo_route_per_asset_when_no_explicit_"
            "gateio_or_gateio_futures_history_route_exists"
        ),
        "discovered_route_count": len(raw_routes),
        "fallback_route_count": len(selected),
        "excluded_route_count": len(excluded),
        "excluded_full_gate_route_count": full_gate_excluded,
        "excluded_secondary_yahoo_route_count": secondary_yahoo_excluded,
        "excluded_routes": excluded,
        "routes": selected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter Yahoo discovery to required fallbacks")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source = Path(args.input)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("Yahoo discovery payload must be a JSON object")
    filtered = filter_fallback_routes(payload)
    if not filtered["routes"]:
        raise SystemExit("Yahoo fallback filtering produced an empty route set")

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(filtered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "discovered_route_count": filtered["discovered_route_count"],
                "fallback_route_count": filtered["fallback_route_count"],
                "excluded_route_count": filtered["excluded_route_count"],
                "excluded_full_gate_route_count": filtered[
                    "excluded_full_gate_route_count"
                ],
                "excluded_secondary_yahoo_route_count": filtered[
                    "excluded_secondary_yahoo_route_count"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
