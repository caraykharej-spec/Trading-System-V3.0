"""Build the authoritative pre-backtest historical-data qualification manifest.

The live Storm universe is the source of truth. Gate and Yahoo history are
accepted only when their route identity is compatible with the Storm base
asset and the reviewed source registry. This prevents ticker collisions such
as Storm SPX being accidentally satisfied by an unrelated Gate crypto market.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from app.data.source_registry import SourceMapping, SourceMappingRegistry, SourceRoute
from app.universe.storm_discovery import StormReferenceAsset, StormReferenceUniverseProvider
from scripts.backtest import hf_s3

_SCHEMA_VERSION = 1
_COMPLETE_GATE = {"COMPLETE", "COMPLETE_WITH_RECORDED_GAPS"}
_COMPLETE_YAHOO = {"COMPLETE"}
_GATE_FULL_PROVIDERS = {"gateio", "gateio_futures"}


def _bucket() -> str:
    value = os.environ.get("HF_S3_BUCKET", "").strip()
    if not value:
        raise RuntimeError("HF_S3_BUCKET is required")
    return value


def _load_hf_json(key: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="global-history-manifest-") as temp_dir:
        target = Path(temp_dir) / "manifest.json"
        hf_s3.aws(
            "s3api",
            "get-object",
            "--bucket",
            _bucket(),
            "--key",
            key,
            str(target),
        )
        payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"manifest is not an object: {key}")
    return payload


def _route_summary_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("route_summaries")
    if not isinstance(raw, list):
        raise ValueError("run manifest is missing route_summaries")
    return [item for item in raw if isinstance(item, dict)]


def _route_key(summary: dict[str, Any]) -> tuple[str, str, str]:
    route = summary.get("route") or {}
    if not isinstance(route, dict):
        return ("", "", "")
    return (
        str(route.get("base_asset") or "").upper(),
        str(route.get("provider") or "").lower(),
        str(route.get("provider_symbol") or "").upper(),
    )


def merge_gate_runs(manifests: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge full Gate run evidence with later repair runs; later wins."""

    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for payload in manifests:
        for summary in _route_summary_list(payload):
            key = _route_key(summary)
            if all(key):
                merged[key] = summary
    return list(merged.values())


def _decimal_equal(left: object, right: Decimal) -> bool:
    try:
        return Decimal(str(left if left is not None else "1")) == right
    except Exception:
        return False


def _route(summary: dict[str, Any]) -> dict[str, Any]:
    value = summary.get("route")
    return value if isinstance(value, dict) else {}


def _explicit_route_matches(summary: dict[str, Any], source: SourceRoute) -> bool:
    route = _route(summary)
    return (
        str(route.get("provider") or "").lower() == source.provider.lower()
        and str(route.get("provider_symbol") or "").upper() == source.symbol.upper()
        and _decimal_equal(route.get("price_multiplier", "1"), source.price_multiplier)
    )


def _dynamic_gate_identity_valid(summary: dict[str, Any], base: str) -> bool:
    route = _route(summary)
    if str(route.get("provider") or "").lower() != "gateio":
        return False
    if str(route.get("route_origin") or "") != "gate_spot_discovery":
        return False
    if not _decimal_equal(route.get("price_multiplier", "1"), Decimal("1")):
        return False
    market = str(route.get("provider_symbol") or "").upper().replace("/", "_")
    provider_base = market.split("_", 1)[0]
    return provider_base == base.upper()


def _preferred_summary(
    base: str,
    mapping: SourceMapping | None,
    gate: list[dict[str, Any]],
    yahoo: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None, list[dict[str, str]]]:
    rejected: list[dict[str, str]] = []
    gate_for_base = [item for item in gate if _route_key(item)[0] == base]
    yahoo_for_base = [
        item
        for item in yahoo
        if str(_route(item).get("base_asset") or "").upper() == base
    ]

    if mapping is None:
        for item in gate_for_base:
            if item.get("status") not in _COMPLETE_GATE:
                continue
            if _dynamic_gate_identity_valid(item, base):
                return item, "gate_dynamic_exact_base", rejected
            rejected.append(
                {
                    "provider": str(_route(item).get("provider") or ""),
                    "provider_symbol": str(_route(item).get("provider_symbol") or ""),
                    "reason": "dynamic_gate_identity_mismatch",
                }
            )
        return None, None, rejected

    # Registry order is authoritative. It captures reviewed aliases and scaling,
    # e.g. TON -> GRAM_USDT and 1000PEPE -> PEPE_USDT * 1000.
    for source in mapping.routes:
        if source.provider in _GATE_FULL_PROVIDERS:
            matches = [
                item
                for item in gate_for_base
                if item.get("status") in _COMPLETE_GATE
                and _explicit_route_matches(item, source)
            ]
            if matches:
                return matches[0], "source_registry", rejected
        elif source.provider == "yahoo":
            matches = [
                item
                for item in yahoo_for_base
                if item.get("status") in _COMPLETE_YAHOO
                and str(_route(item).get("provider_symbol") or "").upper()
                == source.symbol.upper()
                and _decimal_equal(
                    _route(item).get("price_multiplier", "1"), source.price_multiplier
                )
            ]
            if matches:
                return matches[0], "source_registry", rejected

    for item in gate_for_base:
        if item.get("status") not in _COMPLETE_GATE:
            continue
        rejected.append(
            {
                "provider": str(_route(item).get("provider") or ""),
                "provider_symbol": str(_route(item).get("provider_symbol") or ""),
                "reason": "not_an_authorized_registry_route",
            }
        )
    for item in yahoo_for_base:
        if item.get("status") not in _COMPLETE_YAHOO:
            continue
        rejected.append(
            {
                "provider": "yahoo",
                "provider_symbol": str(_route(item).get("provider_symbol") or ""),
                "reason": "not_the_preferred_registry_route",
            }
        )
    return None, None, rejected


def _coverage(summary: dict[str, Any]) -> dict[str, Any]:
    partitions = summary.get("partitions") or []
    if not isinstance(partitions, list):
        partitions = []
    grouped: dict[str, dict[str, Any]] = {}
    first_values: list[str] = []
    last_values: list[str] = []
    stored_rows = 0
    for raw in partitions:
        if not isinstance(raw, dict):
            continue
        timeframe = str(raw.get("timeframe") or "unknown")
        rows = int(raw.get("rows") or 0)
        first = raw.get("first_timestamp")
        last = raw.get("last_timestamp")
        stored_rows += rows
        record = grouped.setdefault(
            timeframe,
            {"rows": 0, "partition_objects": 0, "first_timestamp": None, "last_timestamp": None},
        )
        record["rows"] += rows
        record["partition_objects"] += 1
        if first:
            text = str(first)
            first_values.append(text)
            if record["first_timestamp"] is None or text < record["first_timestamp"]:
                record["first_timestamp"] = text
        if last:
            text = str(last)
            last_values.append(text)
            if record["last_timestamp"] is None or text > record["last_timestamp"]:
                record["last_timestamp"] = text

    route = _route(summary)
    provider = str(route.get("provider") or "yahoo").lower()
    source_rows = (
        int(summary.get("total_5m_rows") or 0)
        if provider in _GATE_FULL_PROVIDERS
        else int(summary.get("total_rows") or 0)
    )
    return {
        "stored_timeframes": sorted(grouped),
        "coverage_by_timeframe": grouped,
        "overall_first_timestamp": min(first_values) if first_values else None,
        "overall_last_timestamp": max(last_values) if last_values else None,
        "source_rows": source_rows,
        "stored_rows_across_timeframes": stored_rows,
        "partition_objects": len([item for item in partitions if isinstance(item, dict)]),
        "recorded_missing_5m_inside_observed_span": int(
            summary.get("missing_5m_inside_observed_span") or 0
        ),
        "source_months_without_rows": list(summary.get("source_months_without_rows") or []),
        "source_ohlc_invariant_rows_dropped": int(
            summary.get("source_ohlc_invariant_rows_dropped") or 0
        ),
        "gap_policy": summary.get("gap_policy"),
    }


def _storm_fingerprint(storm_assets: Iterable[StormReferenceAsset]) -> str:
    payload = [
        {
            "base_asset": item.base_asset.upper(),
            "canonical_symbol": item.canonical_symbol.upper(),
            "provider_symbol": item.provider_symbol,
        }
        for item in sorted(storm_assets, key=lambda item: item.base_asset.upper())
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def qualify(
    storm_assets: Iterable[StormReferenceAsset],
    registry: SourceMappingRegistry,
    gate_summaries: list[dict[str, Any]],
    yahoo_summaries: list[dict[str, Any]],
    *,
    source_manifest_keys: list[str] | None = None,
) -> dict[str, Any]:
    storm = tuple(sorted(storm_assets, key=lambda item: item.base_asset.upper()))
    assets: list[dict[str, Any]] = []
    missing: list[str] = []
    source_counts: dict[str, int] = {}
    rejected_count = 0

    for reference in storm:
        base = reference.base_asset.upper()
        mapping = registry.get(base)
        selected, identity_policy, rejected = _preferred_summary(
            base, mapping, gate_summaries, yahoo_summaries
        )
        rejected_count += len(rejected)
        if selected is None:
            missing.append(base)
            assets.append(
                {
                    "base_asset": base,
                    "storm_canonical_symbol": reference.canonical_symbol,
                    "storm_provider_symbol": reference.provider_symbol,
                    "storm_as_of": reference.as_of.isoformat(),
                    "asset_class": mapping.asset_class if mapping else "storm",
                    "qualification_status": "MISSING_HISTORICAL_SOURCE",
                    "identity_policy": None,
                    "historical_source": None,
                    "rejected_candidates": rejected,
                    "coverage": {},
                }
            )
            continue

        route = _route(selected)
        provider = str(route.get("provider") or "yahoo").lower()
        source_counts[provider] = source_counts.get(provider, 0) + 1
        assets.append(
            {
                "base_asset": base,
                "storm_canonical_symbol": reference.canonical_symbol,
                "storm_provider_symbol": reference.provider_symbol,
                "storm_as_of": reference.as_of.isoformat(),
                "asset_class": mapping.asset_class if mapping else str(route.get("asset_class") or "storm"),
                "qualification_status": "QUALIFIED",
                "identity_policy": identity_policy,
                "historical_source": {
                    "provider": provider,
                    "provider_symbol": route.get("provider_symbol"),
                    "price_multiplier": str(route.get("price_multiplier") or "1"),
                    "route_origin": route.get("route_origin"),
                    "source_status": selected.get("status"),
                    "source_kind": selected.get("source_kind"),
                    "manifest_object_key": selected.get("manifest_object_key"),
                },
                "rejected_candidates": rejected,
                "coverage": _coverage(selected),
            }
        )

    qualified = len(storm) - len(missing)
    return {
        "schema_version": _SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_GLOBAL_HISTORY_QUALIFICATION" if not missing else "FAIL_GLOBAL_HISTORY_QUALIFICATION",
        "authority": "live_storm_reference_universe",
        "identity_policy": "storm_base_asset_plus_reviewed_source_registry_aliases_and_multipliers",
        "storm_universe_fingerprint_sha256": _storm_fingerprint(storm),
        "storm_asset_count": len(storm),
        "qualified_asset_count": qualified,
        "missing_asset_count": len(missing),
        "missing_assets": missing,
        "source_counts": dict(sorted(source_counts.items())),
        "rejected_identity_candidate_count": rejected_count,
        "source_manifest_keys": source_manifest_keys or [],
        "assets": assets,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Global Historical Data Qualification Report",
        "",
        f"- Status: **{payload['status']}**",
        f"- Authority: `{payload['authority']}`",
        f"- Storm assets: **{payload['storm_asset_count']}**",
        f"- Qualified assets: **{payload['qualified_asset_count']}**",
        f"- Missing assets: **{payload['missing_asset_count']}**",
        f"- Rejected identity candidates: **{payload['rejected_identity_candidate_count']}**",
        f"- Storm universe fingerprint: `{payload['storm_universe_fingerprint_sha256']}`",
        "",
        "## Authoritative source by Storm asset",
        "",
        "| Storm asset | Source | Provider symbol | Multiplier | First stored | Last stored | Stored TFs | Stored rows | Objects | Recorded 5m gaps | Status |",
        "|---|---|---|---:|---|---|---|---:|---:|---:|---|",
    ]
    for item in payload["assets"]:
        source = item.get("historical_source") or {}
        coverage = item.get("coverage") or {}
        lines.append(
            "| {base} | {provider} | {symbol} | {multiplier} | {first} | {last} | {tfs} | {rows} | {objects} | {gaps} | {status} |".format(
                base=item["base_asset"],
                provider=source.get("provider") or "-",
                symbol=str(source.get("provider_symbol") or "-").replace("|", "\\|"),
                multiplier=source.get("price_multiplier") or "-",
                first=coverage.get("overall_first_timestamp") or "-",
                last=coverage.get("overall_last_timestamp") or "-",
                tfs=",".join(coverage.get("stored_timeframes") or []) or "-",
                rows=coverage.get("stored_rows_across_timeframes") or 0,
                objects=coverage.get("partition_objects") or 0,
                gaps=coverage.get("recorded_missing_5m_inside_observed_span") or 0,
                status=item["qualification_status"],
            )
        )

    lines.extend(["", "## Per-timeframe coverage", ""])
    for item in payload["assets"]:
        lines.append(f"### {item['base_asset']}")
        source = item.get("historical_source") or {}
        lines.append(
            f"Source: `{source.get('provider') or '-'} / {source.get('provider_symbol') or '-'}`; "
            f"multiplier `{source.get('price_multiplier') or '-'}`; identity `{item.get('identity_policy') or '-'}`."
        )
        coverage = item.get("coverage") or {}
        by_tf = coverage.get("coverage_by_timeframe") or {}
        if not by_tf:
            lines.append("No qualified stored timeframe coverage.")
        else:
            lines.append("")
            lines.append("| Timeframe | First | Last | Rows | Objects |")
            lines.append("|---|---|---|---:|---:|")
            for timeframe in sorted(by_tf):
                record = by_tf[timeframe]
                lines.append(
                    f"| {timeframe} | {record.get('first_timestamp') or '-'} | "
                    f"{record.get('last_timestamp') or '-'} | {record.get('rows') or 0} | "
                    f"{record.get('partition_objects') or 0} |"
                )
        rejected = item.get("rejected_candidates") or []
        if rejected:
            lines.append("")
            lines.append("Rejected candidates: " + "; ".join(
                f"{entry.get('provider')}:{entry.get('provider_symbol')} ({entry.get('reason')})"
                for entry in rejected
            ))
        months = coverage.get("source_months_without_rows") or []
        if months:
            lines.append("")
            lines.append("Source months with no rows: " + ", ".join(months))
        dropped = coverage.get("source_ohlc_invariant_rows_dropped") or 0
        if dropped:
            lines.append("")
            lines.append(f"Invalid source OHLC rows dropped and recorded: {dropped}")
        lines.append("")

    lines.extend(
        [
            "## Qualification rules",
            "",
            "- The live Storm universe is authoritative; Gate/Yahoo do not define membership.",
            "- Reviewed aliases and price multipliers come from `config/market_data/source_registry.json`.",
            "- Dynamic Gate spot routes are accepted only for exact Storm base-asset identity with multiplier 1.",
            "- A same-looking ticker is not enough. Unapproved identity candidates are rejected and reported.",
            "- Yahoo intraday history is source-limited; the report therefore records coverage per timeframe rather than pretending all timeframes have the daily-history range.",
            "- Missing source periods and recorded gaps are preserved; they are never silently filled.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_run_ids(value: str) -> list[str]:
    output = [item.strip() for item in value.split(",") if item.strip()]
    if not output:
        raise ValueError("at least one Gate run id is required")
    if any(not item.isdigit() for item in output):
        raise ValueError("run ids must be numeric")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify Gate+Yahoo history against live Storm universe")
    parser.add_argument("--gate-run-ids", required=True)
    parser.add_argument("--yahoo-run-id", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    gate_ids = _parse_run_ids(args.gate_run_ids)
    if not args.yahoo_run_id.isdigit():
        raise SystemExit("--yahoo-run-id must be numeric")
    gate_keys = [f"manifests/gate-history/v2/runs/{item}.json" for item in gate_ids]
    yahoo_key = f"manifests/yahoo-history/v1/runs/{args.yahoo_run_id}.json"
    gate_manifests = [_load_hf_json(key) for key in gate_keys]
    yahoo_manifest = _load_hf_json(yahoo_key)
    gate_summaries = merge_gate_runs(gate_manifests)
    yahoo_summaries = _route_summary_list(yahoo_manifest)
    storm = StormReferenceUniverseProvider().discover()
    if not storm:
        raise SystemExit("live Storm reference universe is empty")

    payload = qualify(
        storm,
        SourceMappingRegistry.load(),
        gate_summaries,
        yahoo_summaries,
        source_manifest_keys=[*gate_keys, yahoo_key],
    )
    json_path = Path(args.output_json)
    md_path = Path(args.output_md)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "status",
                    "storm_asset_count",
                    "qualified_asset_count",
                    "missing_asset_count",
                    "source_counts",
                    "rejected_identity_candidate_count",
                )
            },
            sort_keys=True,
        )
    )
    if payload["status"] != "PASS_GLOBAL_HISTORY_QUALIFICATION":
        Path(str(json_path) + ".failed").write_text("1\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
