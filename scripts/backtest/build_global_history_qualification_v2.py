"""Backtest-ready route selection and listing-limited qualification policy.

The live Storm universe remains authoritative. Route selection prefers the
first reviewed identity-valid source with sufficient history. Separately,
explicitly reviewed newly-listed markets may qualify as complete datasets even
when strategy warm-up history is not yet long enough. Those assets remain
warm-up blocked until their configured minimum candle requirement is met.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from app.data.source_registry import SourceMapping, SourceMappingRegistry, SourceRoute
from app.data.historical_15m_registry import Historical15mRegistry, Historical15mRoute
from app.universe.storm_discovery import StormReferenceAsset
from scripts.backtest import build_global_history_qualification as legacy

_DEFAULT_LISTING_POLICY = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "market_data"
    / "listing_limited_history.json"
)
_BASE_QUALIFY = legacy.qualify
_BASE_RENDER_MARKDOWN = legacy.render_markdown


def _explicit_gate_matches(
    summary: dict[str, Any], source: SourceRoute
) -> bool:
    route = legacy._route(summary)
    return (
        summary.get("status") in legacy._COMPLETE_GATE
        and str(route.get("provider") or "").lower() == source.provider.lower()
        and str(route.get("provider_symbol") or "").upper() == source.symbol.upper()
        and legacy._decimal_equal(
            route.get("price_multiplier", "1"), source.price_multiplier
        )
    )


def _explicit_yahoo_matches(
    summary: dict[str, Any], source: SourceRoute
) -> bool:
    route = legacy._route(summary)
    return (
        summary.get("status") in legacy._COMPLETE_YAHOO
        and str(route.get("provider_symbol") or "").upper() == source.symbol.upper()
        and legacy._decimal_equal(
            route.get("price_multiplier", "1"), source.price_multiplier
        )
    )


def _explicit_extended_matches(
    summary: dict[str, Any], source: Historical15mRoute
) -> bool:
    route = legacy._route(summary)
    return (
        summary.get("status") in legacy._COMPLETE_EXTENDED_15M
        and str(route.get("base_asset") or "").upper() == source.base_asset
        and str(route.get("provider") or "").lower() == source.provider
        and str(route.get("provider_symbol") or "").upper() == source.symbol
        and legacy._decimal_equal(
            route.get("price_multiplier", "1"), source.price_multiplier
        )
        and str(route.get("route_origin") or "") == "historical_15m_repair_registry"
    )


def _is_ready(summary: dict[str, Any], mapping: SourceMapping | None) -> bool:
    coverage = legacy._coverage(summary)
    _, deficiencies = legacy._coverage_deficiencies(coverage, mapping)
    return not deficiencies


def preferred_summary_backtest_ready(
    base: str,
    mapping: SourceMapping | None,
    gate: list[dict[str, Any]],
    yahoo: list[dict[str, Any]],
    extended_15m: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str | None, list[dict[str, str]]]:
    rejected: list[dict[str, str]] = []

    if mapping is None:
        candidates = [item for item in gate if legacy._route_key(item)[0] == base]
        first_insufficient: dict[str, Any] | None = None
        for item in candidates:
            if item.get("status") not in legacy._COMPLETE_GATE:
                continue
            if not legacy._dynamic_gate_identity_valid(item, base):
                rejected.append(
                    {
                        "provider": str(legacy._route(item).get("provider") or ""),
                        "provider_symbol": str(
                            legacy._route(item).get("provider_symbol") or ""
                        ),
                        "reason": "dynamic_gate_identity_mismatch",
                    }
                )
                continue
            if _is_ready(item, mapping):
                return item, "gate_dynamic_exact_base", rejected
            first_insufficient = first_insufficient or item
        if first_insufficient is not None:
            return first_insufficient, "gate_dynamic_exact_base", rejected
        return None, None, rejected

    # Record same-base completed candidates that are not authorized by the
    # reviewed registry. This makes identity collisions visible even when a
    # valid alternative is ultimately selected (notably SPX_USDT vs ^GSPC).
    authorized_gate = {
        (route.provider.lower(), route.symbol.upper(), route.price_multiplier)
        for route in mapping.routes
        if route.provider in legacy._GATE_FULL_PROVIDERS
    }
    for item in gate:
        if (
            legacy._route_key(item)[0] != base
            or item.get("status") not in legacy._COMPLETE_GATE
        ):
            continue
        route = legacy._route(item)
        identity = (
            str(route.get("provider") or "").lower(),
            str(route.get("provider_symbol") or "").upper(),
            Decimal(str(route.get("price_multiplier") or "1")),
        )
        if identity not in authorized_gate:
            rejected.append(
                {
                    "provider": identity[0],
                    "provider_symbol": identity[1],
                    "reason": "not_an_authorized_registry_route",
                }
            )

    first_insufficient: tuple[dict[str, Any], str] | None = None
    repair_route = Historical15mRegistry.load().get(base)
    if repair_route is not None:
        matches = [
            item
            for item in (extended_15m or [])
            if _explicit_extended_matches(item, repair_route)
        ]
        for item in matches:
            if _is_ready(item, mapping):
                return item, "historical_15m_repair_backtest_ready", rejected
            if first_insufficient is None:
                first_insufficient = (
                    item,
                    "historical_15m_repair_insufficient_history",
                )

    for source in mapping.routes:
        matches: list[dict[str, Any]]
        if source.provider in legacy._GATE_FULL_PROVIDERS:
            # Search all Gate summaries because reviewed aliases such as
            # TON -> GRAM_USDT intentionally use a different provider base.
            matches = [item for item in gate if _explicit_gate_matches(item, source)]
        elif source.provider == "yahoo":
            matches = [item for item in yahoo if _explicit_yahoo_matches(item, source)]
        else:
            continue

        for item in matches:
            if _is_ready(item, mapping):
                return item, "source_registry_backtest_ready", rejected
            if first_insufficient is None:
                first_insufficient = (
                    item,
                    "source_registry_insufficient_history",
                )

    if first_insufficient is not None:
        return first_insufficient[0], first_insufficient[1], rejected
    return None, None, rejected


def load_listing_limited_policy(
    path: Path = _DEFAULT_LISTING_POLICY,
) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_assets = payload.get("assets") or {}
    if not isinstance(raw_assets, dict):
        raise ValueError("listing-limited history policy assets must be an object")
    output: dict[str, dict[str, Any]] = {}
    for base, raw in raw_assets.items():
        if not isinstance(raw, dict):
            raise ValueError(f"listing-limited history policy is invalid for {base}")
        output[str(base).upper()] = dict(raw)
    return output


def _parse_iso(value: object) -> datetime:
    text = str(value or "")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("listing-limited history timestamps must include timezone")
    return parsed


def _listing_policy_matches(
    asset: dict[str, Any], rule: dict[str, Any]
) -> bool:
    if asset.get("qualification_status") != "INSUFFICIENT_BACKTEST_HISTORY":
        return False

    source = asset.get("historical_source") or {}
    if not isinstance(source, dict):
        return False
    if str(source.get("provider") or "").lower() != str(
        rule.get("provider") or ""
    ).lower():
        return False
    if str(source.get("provider_symbol") or "").upper() != str(
        rule.get("provider_symbol") or ""
    ).upper():
        return False

    coverage = asset.get("coverage") or {}
    if not isinstance(coverage, dict):
        return False
    by_timeframe = coverage.get("coverage_by_timeframe") or {}
    if not isinstance(by_timeframe, dict):
        return False
    for timeframe in legacy._REQUIRED_BACKTEST_TIMEFRAMES:
        record = by_timeframe.get(timeframe)
        if not isinstance(record, dict) or int(record.get("rows") or 0) <= 0:
            return False

    actual_start = coverage.get("overall_first_timestamp")
    reviewed_start = rule.get("reviewed_history_start")
    if not actual_start or not reviewed_start:
        return False
    tolerance = int(rule.get("start_tolerance_seconds") or 0)
    delta = abs((_parse_iso(actual_start) - _parse_iso(reviewed_start)).total_seconds())
    return delta <= tolerance


def apply_listing_limited_policy(
    payload: dict[str, Any],
    policy: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    assets = payload.get("assets") or []
    if not isinstance(assets, list):
        raise ValueError("qualification payload assets must be a list")

    converted: list[str] = []
    for raw_asset in assets:
        if not isinstance(raw_asset, dict):
            continue
        base = str(raw_asset.get("base_asset") or "").upper()
        rule = policy.get(base)
        if rule is None or not _listing_policy_matches(raw_asset, rule):
            continue

        warmup_deficiencies = list(raw_asset.get("history_deficiencies") or [])
        raw_asset["qualification_status"] = "QUALIFIED_LISTING_LIMITED_HISTORY"
        raw_asset["history_deficiencies"] = []
        raw_asset["warmup_deficiencies"] = warmup_deficiencies
        raw_asset["strategy_warmup_status"] = (
            "PENDING_MINIMUM_CANDLES" if warmup_deficiencies else "READY"
        )
        raw_asset["listing_limited_history"] = {
            "reviewed_history_start": rule.get("reviewed_history_start"),
            "reason": rule.get("reason"),
            "policy": "dataset_complete_since_reviewed_listing_start_no_prelisting_rows_required",
        }
        converted.append(base)

    insufficient = [
        str(item.get("base_asset") or "").upper()
        for item in assets
        if isinstance(item, dict)
        and item.get("qualification_status") == "INSUFFICIENT_BACKTEST_HISTORY"
    ]
    missing = list(payload.get("missing_assets") or [])
    total = int(payload.get("storm_asset_count") or len(assets))
    payload["listing_limited_asset_count"] = len(converted)
    payload["listing_limited_assets"] = sorted(converted)
    payload["insufficient_history_assets"] = insufficient
    payload["insufficient_history_asset_count"] = len(insufficient)
    payload["qualified_asset_count"] = total - len(missing) - len(insufficient)
    payload["status"] = (
        "FAIL_GLOBAL_HISTORY_QUALIFICATION"
        if missing or insufficient
        else "PASS_GLOBAL_HISTORY_QUALIFICATION"
    )
    history_policy = payload.get("backtest_history_policy")
    if isinstance(history_policy, dict):
        history_policy["listing_limited_dataset_policy"] = (
            "reviewed newly-listed markets may qualify with complete post-listing data; "
            "strategy warm-up remains blocked until minimum candle requirements are met"
        )
    return payload


def qualify_backtest_ready(
    storm_assets: Iterable[StormReferenceAsset],
    registry: SourceMappingRegistry,
    gate_summaries: list[dict[str, Any]],
    yahoo_summaries: list[dict[str, Any]],
    extended_15m_summaries: list[dict[str, Any]] | None = None,
    *,
    source_manifest_keys: list[str] | None = None,
) -> dict[str, Any]:
    payload = _BASE_QUALIFY(
        storm_assets,
        registry,
        gate_summaries,
        yahoo_summaries,
        extended_15m_summaries or [],
        source_manifest_keys=source_manifest_keys,
    )
    return apply_listing_limited_policy(payload, load_listing_limited_policy())


def render_markdown_backtest_ready(payload: dict[str, Any]) -> str:
    base = _BASE_RENDER_MARKDOWN(payload)
    listing_assets = payload.get("listing_limited_assets") or []
    if not listing_assets:
        return base

    lines = [
        base.rstrip(),
        "",
        "## Listing-limited qualified datasets",
        "",
        "These datasets are complete from their reviewed market-history start, but strategy "
        "warm-up remains blocked until the normal minimum candle threshold is reached.",
        "",
    ]
    for item in payload.get("assets") or []:
        if not isinstance(item, dict):
            continue
        if item.get("qualification_status") != "QUALIFIED_LISTING_LIMITED_HISTORY":
            continue
        policy = item.get("listing_limited_history") or {}
        deficiencies = item.get("warmup_deficiencies") or []
        detail = "; ".join(
            f"{entry.get('timeframe')} {entry.get('available_rows')}/{entry.get('required_rows')} rows"
            for entry in deficiencies
            if isinstance(entry, dict)
        )
        lines.append(
            f"- **{item.get('base_asset')}** — reviewed start "
            f"`{policy.get('reviewed_history_start')}`; warm-up "
            f"`{item.get('strategy_warmup_status')}`"
            + (f"; {detail}" if detail else "")
            + "."
        )
    lines.extend(
        [
            "",
            "Listing-limited qualification never creates pre-listing candles and does not "
            "relax source identity, gap preservation, or minimum warm-up requirements.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    legacy._preferred_summary = preferred_summary_backtest_ready
    legacy.qualify = qualify_backtest_ready
    legacy.render_markdown = render_markdown_backtest_ready
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
