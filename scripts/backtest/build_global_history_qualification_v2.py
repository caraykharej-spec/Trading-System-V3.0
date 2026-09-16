"""Backtest-ready route selection extension for global history qualification.

This module keeps the report/output contract from v1 but changes route
selection from "first transferred route" to "first reviewed route that is
both identity-valid and deep enough for the project's required timeframes".
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.data.source_registry import SourceMapping, SourceRoute
from scripts.backtest import build_global_history_qualification as legacy


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


def _is_ready(summary: dict[str, Any], mapping: SourceMapping | None) -> bool:
    coverage = legacy._coverage(summary)
    _, deficiencies = legacy._coverage_deficiencies(coverage, mapping)
    return not deficiencies


def preferred_summary_backtest_ready(
    base: str,
    mapping: SourceMapping | None,
    gate: list[dict[str, Any]],
    yahoo: list[dict[str, Any]],
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
        if legacy._route_key(item)[0] != base or item.get("status") not in legacy._COMPLETE_GATE:
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
                first_insufficient = (item, "source_registry_insufficient_history")

    if first_insufficient is not None:
        return first_insufficient[0], first_insufficient[1], rejected
    return None, None, rejected


def main() -> int:
    legacy._preferred_summary = preferred_summary_backtest_ready
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
