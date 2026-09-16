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


def test_filter_keeps_tradfi_primary_and_reviewed_redundant_yahoo_routes() -> None:
    payload = {
        "routes": [
            _route("AAPL", "AAPL"),
            _route("SPX", "^GSPC"),
            _route("SPX", "ES=F"),
            _route("TON", "TON11419-USD"),
            _route("1000PEPE", "PEPE24478-USD"),
        ]
    }

    filtered = subject.filter_fallback_routes(payload)

    assert [(route["base_asset"], route["provider_symbol"]) for route in filtered["routes"]] == [
        ("AAPL", "AAPL"),
        ("SPX", "^GSPC"),
        ("TON", "TON11419-USD"),
    ]
    assert filtered["discovered_route_count"] == 5
    assert filtered["fallback_route_count"] == 3
    assert filtered["excluded_route_count"] == 2
    assert filtered["excluded_full_gate_route_count"] == 1
    assert filtered["excluded_secondary_yahoo_route_count"] == 1
    reasons = {(item["base_asset"], item["provider_symbol"]): item["reason"] for item in filtered["excluded_routes"]}
    assert reasons[("1000PEPE", "PEPE24478-USD")] == "explicit_full_history_gate_route_available"
    assert reasons[("SPX", "ES=F")] == "secondary_yahoo_route_not_selected_for_historical_archive"


def test_project_registry_yahoo_fallback_count_is_27() -> None:
    from scripts.backtest.sync_yahoo_history_to_hf import discover_routes

    payload = {"routes": [route.__dict__ for route in discover_routes()]}
    filtered = subject.filter_fallback_routes(payload)

    selected = {(route["base_asset"], route["provider_symbol"]) for route in filtered["routes"]}
    assert filtered["fallback_route_count"] == 27
    assert ("SPX", "^GSPC") in selected
    assert ("SPX", "ES=F") not in selected
    assert ("TON", "TON11419-USD") in selected
    assert all(base != "1000PEPE" for base, _ in selected)
