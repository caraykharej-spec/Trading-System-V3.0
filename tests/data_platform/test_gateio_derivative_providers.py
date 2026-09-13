from __future__ import annotations

from decimal import Decimal

from app.data.market_data import MarketDataRequest
from app.data.providers.gateio_futures import GateIOFuturesProvider
from app.data.providers.gateio_tradfi import GateIOTradFiProvider
from app.data.source_registry import SourceMappingRegistry, SourceRoute
from app.universe.market_data_resolution import (
    AssetDataResolution,
    ResolutionSource,
    StormDrivenUniverseResolver,
)


class FuturesClient:
    def get_json(self, url: str) -> object:
        if "/tickers?contract=PEPE_USDT" in url:
            return [{"contract": "PEPE_USDT", "last": "0.0000034"}]
        if "/candlesticks?contract=PEPE_USDT" in url:
            return [{"t": 1_700_000_000, "o": "1", "h": "3", "l": "0.5", "c": "2", "sum": "99"}]
        raise AssertionError(url)


class TradFiClient:
    def get_json(self, url: str) -> object:
        if url.endswith("/tradfi/symbols/AAPL/tickers"):
            return {"data": {"last_price": "332.59"}}
        if "/tradfi/symbols/AAPL/klines" in url:
            return {"data": {"list": [{"t": 1_700_000_000, "o": "330", "h": "334", "l": "329", "c": "332"}]}}
        raise AssertionError(url)


def test_gateio_futures_public_price_and_candles() -> None:
    provider = GateIOFuturesProvider(client=FuturesClient())  # type: ignore[arg-type]
    assert provider.get_live_price("PEPE_USDT").price == Decimal("0.0000034")
    candle = provider.get_candles(MarketDataRequest("PEPE_USDT", "1h", 1))[0]
    assert candle.close == Decimal("2")
    assert candle.volume == Decimal("99")


def test_gateio_tradfi_public_price_and_ohlc() -> None:
    provider = GateIOTradFiProvider(client=TradFiClient())  # type: ignore[arg-type]
    assert provider.get_live_price("AAPL").price == Decimal("332.59")
    candle = provider.get_candles(MarketDataRequest("AAPL", "1h", 1))[0]
    assert candle.close == Decimal("332")
    assert candle.volume == 0


def test_resolver_routes_tradfi_and_applies_split_multiplier() -> None:
    provider = GateIOTradFiProvider(client=TradFiClient())  # type: ignore[arg-type]
    resolver = StormDrivenUniverseResolver(gate_tradfi_provider=provider)
    resolution = AssetDataResolution(
        base_asset="NFLX",
        canonical_symbol="NFLX/USDT",
        storm_reference_price=Decimal("3320"),
        storm_provider_symbol="NFLX/USDT",
        source=ResolutionSource.GATEIO,
        provider_symbol="AAPL",
        provider_price=Decimal("3320"),
        price_deviation_percent=Decimal("0"),
        reason="test",
        market_data_source="gateio_tradfi",
        price_multiplier=Decimal("10"),
        source_routes=(SourceRoute(
            "gateio_tradfi", "AAPL", Decimal("10"), requires_volume=False
        ),),
    )

    candles = resolver.get_candles(
        resolution, timeframe="1h", limit=1, minimum_history=1
    )

    assert candles[0].symbol == "NFLX/USDT"
    assert candles[0].open == Decimal("3300")
    assert candles[0].close == Decimal("3320")


def test_persistent_registry_contains_forex_free_failover() -> None:
    mapping = SourceMappingRegistry.load().get("EUR")

    assert mapping is not None
    assert [(route.provider, route.symbol) for route in mapping.routes] == [
        ("yahoo", "EURUSD=X"),
        ("gateio_tradfi", "EURUSD"),
    ]
    assert all(not route.requires_volume for route in mapping.routes)
