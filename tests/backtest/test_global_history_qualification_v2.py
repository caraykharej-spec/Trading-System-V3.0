from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.data.source_registry import SourceMapping, SourceMappingRegistry, SourceRoute
from app.universe.storm_discovery import StormReferenceAsset
from scripts.backtest import build_global_history_qualification as legacy
from scripts.backtest import build_global_history_qualification_v2 as subject


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


def _parts(rows: int) -> list[dict[str, object]]:
    return [
        {
            "timeframe": timeframe,
            "rows": rows,
            "first_timestamp": "2025-01-01T00:00:00+00:00",
            "last_timestamp": "2026-09-15T00:00:00+00:00",
            "object_key": f"{timeframe}/x",
        }
        for timeframe in ("15m", "1h", "4h", "1d")
    ]


def _gate(
    base: str,
    symbol: str,
    *,
    rows: int = 250,
    origin: str = "source_registry",
) -> dict[str, object]:
    return {
        "status": "COMPLETE",
        "route": {
            "base_asset": base,
            "provider": "gateio",
            "provider_symbol": symbol,
            "price_multiplier": "1",
            "route_origin": origin,
            "asset_class": "crypto",
        },
        "total_5m_rows": rows,
        "partitions": _parts(rows),
    }


def _yahoo(base: str, symbol: str, *, rows: int = 250) -> dict[str, object]:
    return {
        "status": "COMPLETE",
        "route": {
            "base_asset": base,
            "provider_symbol": symbol,
            "price_multiplier": "1",
            "asset_class": "test",
        },
        "total_rows": rows * 4,
        "partitions": _parts(rows),
    }


def test_explicit_reviewed_alias_can_reuse_underlying_verified_gate_series(monkeypatch) -> None:
    registry = SourceMappingRegistry(
        (
            SourceMapping(
                base_asset="TON",
                asset_class="crypto",
                routes=(SourceRoute(provider="gateio", symbol="GRAM_USDT"),),
            ),
        )
    )
    monkeypatch.setattr(legacy, "_preferred_summary", subject.preferred_summary_backtest_ready)

    payload = legacy.qualify(
        [_storm("TON")],
        registry,
        [_gate("GRAM", "GRAM_USDT")],
        [],
    )

    assert payload["status"] == "PASS_GLOBAL_HISTORY_QUALIFICATION"
    source = payload["assets"][0]["historical_source"]
    assert source["provider"] == "gateio"
    assert source["provider_symbol"] == "GRAM_USDT"
    assert payload["assets"][0]["identity_policy"] == "source_registry_backtest_ready"


def test_insufficient_gate_alias_falls_through_to_ready_yahoo(monkeypatch) -> None:
    registry = SourceMappingRegistry(
        (
            SourceMapping(
                base_asset="TON",
                asset_class="crypto",
                routes=(
                    SourceRoute(provider="gateio", symbol="GRAM_USDT"),
                    SourceRoute(provider="yahoo", symbol="TON11419-USD"),
                ),
            ),
        )
    )
    monkeypatch.setattr(legacy, "_preferred_summary", subject.preferred_summary_backtest_ready)

    payload = legacy.qualify(
        [_storm("TON")],
        registry,
        [_gate("TON", "GRAM_USDT", rows=100)],
        [_yahoo("TON", "TON11419-USD", rows=250)],
    )

    assert payload["status"] == "PASS_GLOBAL_HISTORY_QUALIFICATION"
    assert payload["assets"][0]["historical_source"]["provider"] == "yahoo"
    assert payload["assets"][0]["historical_source"]["provider_symbol"] == "TON11419-USD"


def test_spx_collision_is_reported_even_when_yahoo_is_selected(monkeypatch) -> None:
    registry = SourceMappingRegistry(
        (
            SourceMapping(
                base_asset="SPX",
                asset_class="index",
                routes=(SourceRoute(provider="yahoo", symbol="^GSPC"),),
            ),
        )
    )
    monkeypatch.setattr(legacy, "_preferred_summary", subject.preferred_summary_backtest_ready)

    payload = legacy.qualify(
        [_storm("SPX")],
        registry,
        [_gate("SPX", "SPX_USDT", origin="gate_spot_discovery")],
        [_yahoo("SPX", "^GSPC")],
    )

    assert payload["status"] == "PASS_GLOBAL_HISTORY_QUALIFICATION"
    rejected = payload["assets"][0]["rejected_candidates"]
    assert rejected == [
        {
            "provider": "gateio",
            "provider_symbol": "SPX_USDT",
            "reason": "not_an_authorized_registry_route",
        }
    ]


def _listing_asset(base: str, symbol: str, first: str) -> dict[str, object]:
    return {
        "base_asset": base,
        "qualification_status": "INSUFFICIENT_BACKTEST_HISTORY",
        "historical_source": {
            "provider": "gateio",
            "provider_symbol": symbol,
        },
        "history_deficiencies": [
            {
                "timeframe": "1d",
                "required_rows": 200,
                "available_rows": 60,
                "missing_rows": 140,
            }
        ],
        "coverage": {
            "overall_first_timestamp": first,
            "coverage_by_timeframe": {
                timeframe: {
                    "rows": 60,
                    "first_timestamp": first,
                    "last_timestamp": "2026-09-15T00:00:00+00:00",
                }
                for timeframe in ("15m", "1h", "4h", "1d")
            },
        },
    }


def test_reviewed_listing_limited_asset_qualifies_dataset_but_keeps_warmup_blocked() -> None:
    payload = {
        "storm_asset_count": 2,
        "qualified_asset_count": 0,
        "missing_assets": [],
        "insufficient_history_assets": ["SPCX", "TON"],
        "insufficient_history_asset_count": 2,
        "status": "FAIL_GLOBAL_HISTORY_QUALIFICATION",
        "backtest_history_policy": {},
        "assets": [
            _listing_asset("SPCX", "SPCX_USDT", "2026-04-24T10:00:00+00:00"),
            _listing_asset("TON", "GRAM_USDT", "2026-06-16T00:00:00+00:00"),
        ],
    }
    policy = {
        "SPCX": {
            "provider": "gateio",
            "provider_symbol": "SPCX_USDT",
            "reviewed_history_start": "2026-04-24T10:00:00+00:00",
            "start_tolerance_seconds": 3600,
            "reason": "newly listed",
        }
    }

    result = subject.apply_listing_limited_policy(payload, policy)

    assert result["qualified_asset_count"] == 1
    assert result["listing_limited_assets"] == ["SPCX"]
    assert result["insufficient_history_assets"] == ["TON"]
    assert result["status"] == "FAIL_GLOBAL_HISTORY_QUALIFICATION"
    spcx = result["assets"][0]
    assert spcx["qualification_status"] == "QUALIFIED_LISTING_LIMITED_HISTORY"
    assert spcx["history_deficiencies"] == []
    assert spcx["strategy_warmup_status"] == "PENDING_MINIMUM_CANDLES"
    assert spcx["warmup_deficiencies"][0]["timeframe"] == "1d"
    assert result["assets"][1]["qualification_status"] == "INSUFFICIENT_BACKTEST_HISTORY"


def test_listing_limited_policy_fails_closed_when_history_start_does_not_match() -> None:
    payload = {
        "storm_asset_count": 1,
        "qualified_asset_count": 0,
        "missing_assets": [],
        "insufficient_history_assets": ["SKY"],
        "insufficient_history_asset_count": 1,
        "status": "FAIL_GLOBAL_HISTORY_QUALIFICATION",
        "backtest_history_policy": {},
        "assets": [
            _listing_asset("SKY", "SKY_USDT", "2025-10-01T00:00:00+00:00")
        ],
    }
    policy = {
        "SKY": {
            "provider": "gateio",
            "provider_symbol": "SKY_USDT",
            "reviewed_history_start": "2025-09-17T13:00:00+00:00",
            "start_tolerance_seconds": 3600,
            "reason": "reviewed September listing",
        }
    }

    result = subject.apply_listing_limited_policy(payload, policy)

    assert result["listing_limited_asset_count"] == 0
    assert result["qualified_asset_count"] == 0
    assert result["insufficient_history_assets"] == ["SKY"]
    assert result["status"] == "FAIL_GLOBAL_HISTORY_QUALIFICATION"
