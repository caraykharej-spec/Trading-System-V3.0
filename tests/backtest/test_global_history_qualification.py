from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.data.source_registry import SourceMapping, SourceMappingRegistry, SourceRoute
from app.universe.storm_discovery import StormReferenceAsset
from scripts.backtest import build_global_history_qualification as subject


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


def _partition(timeframe: str = "1d") -> dict[str, object]:
    return {
        "timeframe": timeframe,
        "rows": 10,
        "first_timestamp": "2025-01-01T00:00:00+00:00",
        "last_timestamp": "2026-09-15T00:00:00+00:00",
        "object_key": "x",
    }


def _gate(
    base: str,
    symbol: str,
    *,
    provider: str = "gateio",
    multiplier: str = "1",
    origin: str = "source_registry",
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
        "total_5m_rows": 100,
        "partitions": [_partition()],
    }


def _yahoo(base: str, symbol: str, *, multiplier: str = "1") -> dict[str, object]:
    return {
        "status": "COMPLETE",
        "route": {
            "base_asset": base,
            "provider_symbol": symbol,
            "price_multiplier": multiplier,
            "asset_class": "index",
        },
        "total_rows": 10,
        "partitions": [_partition()],
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
