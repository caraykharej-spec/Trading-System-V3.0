from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.data.source_registry import SourceMapping, SourceMappingRegistry, SourceRoute
from app.universe.storm_discovery import StormReferenceAsset
from scripts.backtest import build_global_history_qualification as subject


def test_extended_15m_manifest_requires_full_26_route_evidence() -> None:
    subject._validate_extended_15m_run_manifest(
        {
            "status": "PASS_COMPLETE_15M_REPAIR",
            "scope": "full",
            "expected_routes": 26,
            "completed_routes": 26,
        }
    )


def test_targeted_extended_15m_manifest_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="complete repair run"):
        subject._validate_extended_15m_run_manifest(
            {
                "status": "PASS_TARGETED_15M_REPAIR",
                "scope": "targeted",
                "expected_routes": 1,
                "completed_routes": 1,
            }
        )


def _storm(base: str) -> StormReferenceAsset:
    return StormReferenceAsset(
        base_asset=base,
        canonical_symbol=f"{base}/USDT",
        provider_symbol=f"{base}/USDT",
        market_type="base",
        settlement="usdt",
        reference_price=Decimal("1"),
        as_of=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )


def _partition(timeframe: str, rows: int = 250) -> dict[str, object]:
    return {
        "timeframe": timeframe,
        "rows": rows,
        "first_timestamp": "2025-01-01T00:00:00+00:00",
        "last_timestamp": "2026-09-15T00:00:00+00:00",
        "object_key": "x",
    }


def _partitions(rows: int = 250) -> list[dict[str, object]]:
    return [_partition(timeframe, rows) for timeframe in ("15m", "1h", "4h", "1d")]


def _gate(
    base: str,
    symbol: str,
    *,
    provider: str = "gateio",
    multiplier: str = "1",
    origin: str = "source_registry",
    rows: int = 250,
) -> dict[str, object]:
    return {
        "status": "COMPLETE",
        "route": {
            "base_asset": base,
            "provider": provider,
            "provider_symbol": symbol,
            "price_multiplier": multiplier,
            "route_origin": origin,
            "asset_class": "storm",
        },
        "total_5m_rows": rows,
        "partitions": _partitions(rows),
    }


def _yahoo(
    base: str, symbol: str, *, multiplier: str = "1", rows: int = 250
) -> dict[str, object]:
    return {
        "status": "COMPLETE",
        "route": {
            "base_asset": base,
            "provider_symbol": symbol,
            "price_multiplier": multiplier,
            "asset_class": "index",
        },
        "total_rows": rows * 4,
        "partitions": _partitions(rows),
    }


def test_aliases_and_identity_collision_are_resolved_from_storm_and_registry() -> None:
    registry = SourceMappingRegistry(
        (
            SourceMapping(
                base_asset="TON",
                asset_class="crypto",
                routes=(SourceRoute(provider="gateio", symbol="GRAM_USDT"),),
            ),
            SourceMapping(
                base_asset="1000PEPE",
                asset_class="crypto",
                routes=(
                    SourceRoute(
                        provider="gateio_futures",
                        symbol="PEPE_USDT",
                        price_multiplier=Decimal("1000"),
                    ),
                ),
            ),
            SourceMapping(
                base_asset="SPX",
                asset_class="index",
                routes=(
                    SourceRoute(provider="yahoo", symbol="^GSPC", requires_volume=False),
                    SourceRoute(provider="yahoo", symbol="ES=F"),
                ),
            ),
        )
    )
    gate = [
        _gate("TON", "GRAM_USDT"),
        _gate("1000PEPE", "PEPE_USDT", provider="gateio_futures", multiplier="1000"),
        _gate("SPX", "SPX_USDT", origin="gate_spot_discovery"),
    ]
    yahoo = [_yahoo("SPX", "^GSPC")]

    payload = subject.qualify(
        [_storm("TON"), _storm("1000PEPE"), _storm("SPX")],
        registry,
        gate,
        yahoo,
    )

    assert payload["status"] == "PASS_GLOBAL_HISTORY_QUALIFICATION"
    assets = {item["base_asset"]: item for item in payload["assets"]}
    assert assets["TON"]["historical_source"]["provider_symbol"] == "GRAM_USDT"
    assert assets["1000PEPE"]["historical_source"]["provider_symbol"] == "PEPE_USDT"
    assert assets["1000PEPE"]["historical_source"]["price_multiplier"] == "1000"
    assert assets["SPX"]["historical_source"]["provider"] == "yahoo"
    assert assets["SPX"]["historical_source"]["provider_symbol"] == "^GSPC"


def test_unmapped_dynamic_gate_requires_exact_storm_base() -> None:
    registry = SourceMappingRegistry(())
    payload = subject.qualify(
        [_storm("BTC")],
        registry,
        [_gate("BTC", "BTC_USDT", origin="gate_spot_discovery")],
        [],
    )
    assert payload["status"] == "PASS_GLOBAL_HISTORY_QUALIFICATION"
    assert payload["assets"][0]["historical_source"]["provider_symbol"] == "BTC_USDT"


def test_missing_storm_asset_fails_global_qualification() -> None:
    payload = subject.qualify(
        [_storm("BTC")],
        SourceMappingRegistry(()),
        [],
        [],
    )
    assert payload["status"] == "FAIL_GLOBAL_HISTORY_QUALIFICATION"
    assert payload["missing_assets"] == ["BTC"]


def test_insufficient_history_fails_even_when_source_sync_is_complete() -> None:
    registry = SourceMappingRegistry(
        (
            SourceMapping(
                base_asset="SPX",
                asset_class="index",
                routes=(SourceRoute(provider="yahoo", symbol="^GSPC"),),
                minimum_candles=220,
            ),
        )
    )
    payload = subject.qualify(
        [_storm("SPX")],
        registry,
        [],
        [_yahoo("SPX", "^GSPC", rows=219)],
    )

    assert payload["status"] == "FAIL_GLOBAL_HISTORY_QUALIFICATION"
    assert payload["insufficient_history_assets"] == ["SPX"]
    asset = payload["assets"][0]
    assert asset["qualification_status"] == "INSUFFICIENT_BACKTEST_HISTORY"
    assert {item["timeframe"] for item in asset["history_deficiencies"]} == {
        "15m",
        "1h",
        "4h",
        "1d",
    }

def test_merge_gate_runs_preserves_continuity_against_later_plain_repair() -> None:
    continuity = _gate(
        "TON",
        "GRAM_USDT",
        origin="source_registry_historical_symbol_continuity",
        rows=783,
    )
    continuity["historical_symbol_continuity"] = {
        "target_provider_symbol": "GRAM_USDT",
        "segments": [
            {
                "source_provider_symbol": "TON_USDT",
                "start": "2023-01-01T00:00:00+00:00",
                "end": "2026-06-16T14:00:00+00:00",
            },
            {
                "source_provider_symbol": "GRAM_USDT",
                "start": "2026-06-16T14:00:00+00:00",
                "end": None,
            },
        ],
        "stitch_policy": "exact_timestamp_union_fail_on_conflict_no_synthetic_rows",
    }
    plain_repair = _gate("TON", "GRAM_USDT", rows=80)

    merged = subject.merge_gate_runs(
        [
            {"route_summaries": [continuity]},
            {"route_summaries": [plain_repair]},
        ]
    )

    assert len(merged) == 1
    assert merged[0]["total_5m_rows"] == 783
    assert (
        merged[0]["route"]["route_origin"]
        == "source_registry_historical_symbol_continuity"
    )


def test_merge_gate_runs_keeps_later_wins_for_plain_routes() -> None:
    merged = subject.merge_gate_runs(
        [
            {"route_summaries": [_gate("BTC", "BTC_USDT", rows=250)]},
            {"route_summaries": [_gate("BTC", "BTC_USDT", rows=300)]},
        ]
    )

    assert len(merged) == 1
    assert merged[0]["total_5m_rows"] == 300
