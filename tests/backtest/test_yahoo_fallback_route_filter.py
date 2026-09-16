from __future__ import annotations

from scripts.backtest import filter_yahoo_fallback_routes as subject


def _route(base_asset: str, provider_symbol: str) -> dict[str, object]:
    return {
        "canonical_symbol": base_asset,
        "base_asset": base_asset,
        "asset_class": "test",
        "provider_symbol": provider_symbol,
        "price_multiplier": "1",
        "requires_volume": True,
    }


def test_filter_keeps_tradfi_and_yahoo_only_routes() -> None:
    payload = {
        "routes": [
            _route("AAPL", "AAPL"),
            _route("SPX", "^GSPC"),
            _route("TON", "TON11419-USD"),
            _route("1000PEPE", "PEPE24478-USD"),
        ]
    }

    filtered = subject.filter_fallback_routes(payload)

    assert [route["base_asset"] for route in filtered["routes"]] == ["AAPL", "SPX"]
    assert filtered["discovered_route_count"] == 4
    assert filtered["fallback_route_count"] == 2
    assert filtered["excluded_full_gate_route_count"] == 2
    assert {item["base_asset"] for item in filtered["excluded_routes"]} == {
        "TON",
        "1000PEPE",
    }


def test_project_registry_yahoo_fallback_count_is_26() -> None:
    from scripts.backtest.sync_yahoo_history_to_hf import discover_routes

    payload = {"routes": [route.__dict__ for route in discover_routes()]}
    filtered = subject.filter_fallback_routes(payload)

    bases = {route["base_asset"] for route in filtered["routes"]}
    assert filtered["fallback_route_count"] == 26
    assert "SPX" in bases
    assert "TON" not in bases
    assert "1000PEPE" not in bases
