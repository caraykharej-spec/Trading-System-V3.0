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
