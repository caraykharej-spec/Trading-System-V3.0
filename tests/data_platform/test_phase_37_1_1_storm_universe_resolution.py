from __future__ import annotations

from decimal import Decimal

from app.data.providers.gateio import GateIOProvider
from app.data.providers.storm import StormProvider
from app.data.providers.yahoo import YahooFinanceProvider
from app.universe.gateio_discovery import GateIOSpotDiscoveryProvider
from app.universe.market_data_resolution import (
    ResolutionSource,
    StormDrivenUniverseResolver,
)
from app.universe.storm_discovery import StormReferenceUniverseProvider
from interfaces.api.service import TradingApiService


class StormHttpClient:
    def get_json(self, url: str) -> object:
        assert url.endswith("/markets")
        return {
            "data": [
                {
                    "config": {
                        "ticker": "BTC/USD-CM",
                        "baseAsset": "BTC",
                        "type": "coinm",
                        "settlementToken": "NOT",
                    },
                    "amm": {"indexPrice": "999000000000"},
                },
                {
                    "config": {
                        "ticker": "BTC/USDT",
                        "baseAsset": "BTC",
                        "type": "base",
                        "settlementToken": "USDT",
                    },
                    "amm": {"indexPrice": "100000000000"},
                },
                {
                    "config": {
                        "ticker": "ETH/USDT",
                        "baseAsset": "ETH",
                        "type": "base",
                        "settlementToken": "USDT",
                    },
                    "amm": {"indexPrice": "200000000000"},
                },
                {
                    "config": {
                        "ticker": "ABC/USDT",
                        "baseAsset": "ABC",
                        "type": "base",
                        "settlementToken": "USDT",
                    },
                    "amm": {"indexPrice": "50000000000"},
                },
                {
                    "config": {
                        "ticker": "XRP/USDT",
                        "baseAsset": "XRP",
                        "type": "index",
                        "settlementToken": "USDT",
                    },
                    "amm": {"indexPrice": "1000000000"},
                },
                {
                    "config": {
                        "ticker": "SOL/USDC",
                        "baseAsset": "SOL",
                        "type": "base",
                        "settlementToken": "USDC",
                    },
                    "amm": {"indexPrice": "150000000000"},
                },
                {
                    "config": {
                        "ticker": "CLOSED/USDT",
                        "baseAsset": "CLOSED",
                        "type": "base",
                        "settlementToken": "USDT",
                    },
                    "settings": {"status": "active", "isCloseOnly": True},
                    "amm": {"indexPrice": "1000000000"},
                },
                {
                    "config": {
                        "ticker": "HIDDEN/USDT",
                        "baseAsset": "HIDDEN",
                        "type": "base",
                        "settlementToken": "USDT",
                        "isHidden": True,
                    },
                    "settings": {"status": "active"},
                    "amm": {"indexPrice": "1000000000"},
                },
            ]
        }


class GateHttpClient:
    def get_json(self, url: str) -> object:
        if url.endswith("/spot/currency_pairs"):
            return [
                {
                    "id": "BTC_USDT",
                    "base": "BTC",
                    "quote": "USDT",
                    "trade_status": "tradable",
                    "type": "normal",
                },
                {
                    "id": "BTC_USDC",
                    "base": "BTC",
                    "quote": "USDC",
                    "trade_status": "tradable",
                    "type": "normal",
                },
                {
                    "id": "BTC_ETH",
                    "base": "BTC",
                    "quote": "ETH",
                    "trade_status": "tradable",
                    "type": "normal",
                },
                {
                    "id": "ETH_USDT",
                    "base": "ETH",
                    "quote": "USDT",
                    "trade_status": "tradable",
                    "type": "normal",
                },
            ]
        if url.endswith("/spot/tickers"):
            return [
                {"currency_pair": "BTC_USDT", "last": "101.00"},
                {"currency_pair": "BTC_USDC", "last": "100.20"},
                {"currency_pair": "BTC_ETH", "last": "2.00"},
                {"currency_pair": "ETH_USDT", "last": "230.00"},
            ]
        if "currency_pair=BTC_USDC" in url and "/spot/candlesticks" in url:
            return [["1757583900", "10", "100.3", "100.5", "99.8", "100.0"]]
        raise AssertionError(f"unexpected Gate.io URL: {url}")


class YahooHttpClient:
    def get_json(self, url: str) -> object:
        if "ETH-USD" in url:
            return {
                "chart": {
                    "result": [{"meta": {"regularMarketPrice": 199.0}}],
                    "error": None,
                }
            }
        return {
            "chart": {
                "result": None,
                "error": {"code": "Not Found", "description": "No data"},
            }
        }


def _resolver() -> StormDrivenUniverseResolver:
    storm = StormProvider(client=StormHttpClient())  # type: ignore[arg-type]
    gate_client = GateHttpClient()
    yahoo = YahooFinanceProvider(client=YahooHttpClient())  # type: ignore[arg-type]
    return StormDrivenUniverseResolver(
        storm_universe=StormReferenceUniverseProvider(provider=storm),
        gate_discovery=GateIOSpotDiscoveryProvider(client=gate_client),  # type: ignore[arg-type]
        gate_provider=GateIOProvider(client=gate_client),  # type: ignore[arg-type]
        yahoo_provider=yahoo,
        max_price_deviation_percent=Decimal("5"),
    )


def test_storm_nested_schema_filters_reference_universe_and_scales_price() -> None:
    storm = StormProvider(client=StormHttpClient())  # type: ignore[arg-type]
    assets = StormReferenceUniverseProvider(provider=storm).discover()

    assert [asset.base_asset for asset in assets] == ["ABC", "BTC", "ETH"]
    btc = next(asset for asset in assets if asset.base_asset == "BTC")
    assert btc.provider_symbol == "BTC/USDT"
    assert btc.reference_price == Decimal("100")


def test_storm_live_price_prefers_base_usdt_market_over_coin_margined_market() -> None:
    storm = StormProvider(client=StormHttpClient())  # type: ignore[arg-type]

    live = storm.get_live_price("BTC")

    assert live.price == Decimal("100")
    assert live.provider == "storm"


def test_storm_is_reference_universe_and_coverage_buckets_are_exhaustive() -> None:
    report = _resolver().resolve()

    assert report.reference_storm == 3
    assert report.gateio == 1
    assert report.yfinance == 1
    assert report.no_data == 1
    assert report.gateio + report.yfinance + report.no_data == report.reference_storm
    assert report.resolved == 2
    assert report.coverage_percent == Decimal("66.67")


def test_gateio_selects_closest_comparable_price_to_storm() -> None:
    report = _resolver().resolve()
    btc = next(item for item in report.assets if item.base_asset == "BTC")

    assert btc.source is ResolutionSource.GATEIO
    assert btc.provider_symbol == "BTC_USDC"
    assert btc.provider_price == Decimal("100.20")
    assert btc.price_deviation_percent == Decimal("0.200")


def test_gateio_price_mismatch_falls_back_to_yahoo() -> None:
    report = _resolver().resolve()
    eth = next(item for item in report.assets if item.base_asset == "ETH")

    assert eth.source is ResolutionSource.YFINANCE
    assert eth.provider_symbol == "ETH-USD"
    assert eth.provider_price == Decimal("199.0")
    assert eth.price_deviation_percent == Decimal("0.500")


def test_unresolved_asset_is_reported_instead_of_silently_dropped() -> None:
    report = _resolver().resolve()
    abc = next(item for item in report.assets if item.base_asset == "ABC")

    assert abc.source is ResolutionSource.NO_DATA
    assert "gateio_not_found" in abc.reason
    assert "yfinance_not_found" in abc.reason


def test_selected_provider_fetches_ohlcv_and_restores_canonical_symbol() -> None:
    resolver = _resolver()
    report = resolver.resolve()
    btc = next(item for item in report.assets if item.base_asset == "BTC")

    candles = resolver.get_candles(btc, timeframe="15m", limit=1)

    assert len(candles) == 1
    assert candles[0].symbol == "BTC/USDT"
    assert candles[0].close == Decimal("100.3")


def test_api_report_uses_requested_storm_gate_yfinance_no_data_counts() -> None:
    resolver = _resolver()
    service = TradingApiService(universe_coverage_provider=resolver.resolve)

    response = service.universe_coverage()

    assert response.status_code == 200
    coverage = response.body["universe_coverage"]
    assert coverage["reference_storm"] == 3
    assert coverage["gateio"] == 1
    assert coverage["yfinance"] == 1
    assert coverage["no_data"] == 1


def test_live_report_builds_read_only_mappings_and_conservative_specs() -> None:
    report = _resolver().resolve()
    mappings = report.symbol_mappings()
    specs = report.research_contract_specs()

    assert any(
        item.canonical == "BTC/USDT"
        and item.provider == "gateio"
        and item.provider_symbol == "BTC_USDC"
        for item in mappings
    )
    assert any(
        item.canonical == "ETH/USDT"
        and item.provider == "yahoo"
        and item.provider_symbol == "ETH-USD"
        for item in mappings
    )
    assert specs["BTC/USDT"].max_leverage == Decimal("1")
