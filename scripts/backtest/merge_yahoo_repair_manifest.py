"""Merge a targeted Yahoo route repair into a prior run manifest.

A repair run should not re-fetch every healthy Yahoo route. This module replaces
only the explicitly repaired route summary in a prior manifest and revalidates
the complete run accounting before a new authoritative run manifest is
published.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def _route(summary: dict[str, Any]) -> dict[str, Any]:
    value = summary.get("route")
    if not isinstance(value, dict):
        raise ValueError("Yahoo route summary is missing route metadata")
    return value


def _identity(summary: dict[str, Any]) -> tuple[str, str, Decimal]:
    route = _route(summary)
    base = str(route.get("base_asset") or "").strip().upper()
    symbol = str(route.get("provider_symbol") or "").strip().upper()
    try:
        multiplier = Decimal(str(route.get("price_multiplier") or "1"))
    except InvalidOperation as exc:
        raise ValueError("Yahoo route has invalid price_multiplier") from exc
    if not base or not symbol:
        raise ValueError("Yahoo route identity requires base_asset and provider_symbol")
    return base, symbol, multiplier


def merge_repair(
    base_manifest: dict[str, Any],
    repair_summaries: list[dict[str, Any]],
    *,
    github_run_id: str | None,
    github_sha: str | None,
    base_run_id: str,
    sync_result: str,
) -> dict[str, Any]:
    raw_base = base_manifest.get("route_summaries")
    if not isinstance(raw_base, list) or not raw_base:
        raise ValueError("Base Yahoo manifest has no route_summaries")
    base_summaries = [item for item in raw_base if isinstance(item, dict)]
    expected = int(base_manifest.get("expected_routes") or len(base_summaries))
    if expected != len(base_summaries):
        raise ValueError(
            f"Base Yahoo manifest accounting mismatch: expected={expected}, summaries={len(base_summaries)}"
        )
    if not repair_summaries:
        raise ValueError("Repair run produced no route summary")

    merged = list(base_summaries)
    repaired: list[dict[str, str]] = []
    for repair in repair_summaries:
        if repair.get("status") != "COMPLETE":
            raise ValueError("Repair summary is not COMPLETE")
        identity = _identity(repair)
        matches = [index for index, item in enumerate(merged) if _identity(item) == identity]
        if len(matches) != 1:
            raise ValueError(
                "Repair route must match exactly one base summary: "
                f"{identity[0]} / {identity[1]} (matches={len(matches)})"
            )
        merged[matches[0]] = repair
        repaired.append(
            {
                "base_asset": identity[0],
                "provider_symbol": identity[1],
                "price_multiplier": str(identity[2]),
            }
        )

    complete = sum(item.get("status") == "COMPLETE" for item in merged)
    errors = sum(item.get("status") == "ERROR" for item in merged)
    missing = max(0, expected - len(merged))
    failed = sync_result != "success" or complete != expected or errors or missing
    return {
        "schema_version": 4,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "github_run_id": github_run_id,
        "github_sha": github_sha,
        "selection_policy": "backtest_ready_yahoo_routes_targeted_repair_composite",
        "repair_base_run_id": base_run_id,
        "repaired_routes": repaired,
        "status": (
            "FAIL_INCOMPLETE_YAHOO_TRANSFER" if failed else "PASS_COMPLETE_YAHOO_TRANSFER"
        ),
        "expected_routes": expected,
        "received_route_summaries": len(merged),
        "completed_routes": complete,
        "error_routes": errors,
        "missing_route_summaries": missing,
        "total_rows": sum(int(item.get("total_rows", 0)) for item in merged),
        "partition_objects_recorded": sum(
            int(item.get("partition_objects_recorded", 0)) for item in merged
        ),
        "route_summaries": merged,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge targeted Yahoo repair evidence")
    parser.add_argument("--base-manifest", required=True)
    parser.add_argument("--repair-dir", required=True)
    parser.add_argument("--base-run-id", required=True)
    parser.add_argument("--sync-result", required=True)
    parser.add_argument("--github-run-id")
    parser.add_argument("--github-sha")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    base = json.loads(Path(args.base_manifest).read_text(encoding="utf-8"))
    if not isinstance(base, dict):
        raise SystemExit("Base Yahoo manifest must be a JSON object")
    repair_summaries = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(Path(args.repair_dir).rglob("route-summary.json"))
    ]
    payload = merge_repair(
        base,
        repair_summaries,
        github_run_id=args.github_run_id,
        github_sha=args.github_sha,
        base_run_id=args.base_run_id,
        sync_result=args.sync_result,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "status",
                    "expected_routes",
                    "completed_routes",
                    "error_routes",
                    "missing_route_summaries",
                    "total_rows",
                    "partition_objects_recorded",
                    "repair_base_run_id",
                    "repaired_routes",
                )
            },
            sort_keys=True,
        )
    )
    if payload["status"] != "PASS_COMPLETE_YAHOO_TRANSFER":
        Path(str(output) + ".failed").write_text("1\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
