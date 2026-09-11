from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from app.data.cache import MarketDataCache
from app.data.historical_store import InMemoryCandleStore
from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.platform import ProductionMarketDataPlatform
from app.data.provider_registry import ProviderRole, build_default_provider_registry
from app.data.provider_router import ProviderRouter
from app.data.providers.gateio_stream import (
    GateIOCandleSubscription,
    GateIOWebSocketCandleSource,
)
from app.data.streaming import CandleStreamEvent, CandleStreamIngestor
from app.data.time_sync import ClockSkewMonitor
from app.universe.gateio_discovery import GateIOSpotDiscoveryProvider


class FakeHttpClient:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def get_json(self, url: str) -> object:
        assert url.endswith("/spot/currency_pairs")
        return self.payload


class FakeProvider:
    name = "fake"

    def get_live_price(self, symbol: str) -> LivePrice:
        return LivePrice(
            symbol=symbol,
            price=Decimal("100"),
            as_of=datetime.now(timezone.utc),
            provider=self.name,
        )

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        return []


def test_default_provider_registry_preserves_explicit_source_roles() -> None:
    registry = build_default_provider_registry()

    assert [item.name for item in registry.for_role(ProviderRole.LIVE_PRICE)] == ["storm"]
    assert [item.name for item in registry.for_role(ProviderRole.OHLCV_STREAM)] == ["gateio"]
    assert registry.get("gateio").public_no_key is True
    assert registry.get("gateio").transports == ("HTTPS", "WSS")
    assert registry.get("yahoo").roles == frozenset({ProviderRole.OHLCV_REST})


def test_gateio_discovery_normalizes_public_spot_metadata() -> None:
    provider = GateIOSpotDiscoveryProvider(
        client=FakeHttpClient(
            [
                {
                    "id": "ETH_USDT",
                    "base": "ETH",
                    "quote": "USDT",
                    "min_base_amount": "0.001",
                    "amount_precision": 3,
                    "precision": 6,
                    "trade_status": "tradable",
                    "type": "normal",
                },
                {
                    "id": "ABC_USDT",
                    "base": "ABC",
                    "quote": "USDT",
                    "min_base_amount": "1",
                    "amount_precision": 0,
                    "precision": 4,
                    "trade_status": "untradable",
                    "type": "normal",
                },
            ]
        )
    )

    instruments = provider.discover_instruments()

    assert [item.symbol for item in instruments] == ["ABC/USDT", "ETH/USDT"]
    eth = next(item for item in instruments if item.symbol == "ETH/USDT")
    assert eth.tradable is True
    assert eth.min_quantity == Decimal("0.001")
    assert eth.quantity_step == Decimal("0.001")
    assert eth.price_tick == Decimal("0.000001")


def test_clock_monitor_tracks_provider_timestamp_skew() -> None:
    monitor = ClockSkewMonitor(max_allowed_skew_ms=1_000, alpha=1.0)
    received = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)

    snapshot = monitor.observe(int(received.timestamp() * 1000) + 250, received_at=received)

    assert snapshot.samples == 1
    assert snapshot.observed_offset_ms == 250.0
    assert snapshot.healthy is True


def test_gateio_websocket_parses_public_candle_update() -> None:
    source = GateIOWebSocketCandleSource(
        (
            GateIOCandleSubscription(
                canonical_symbol="BTC/USDT",
                provider_symbol="BTC_USDT",
                timeframe="15m",
            ),
        )
    )
    message = json.dumps(
        {
            "time": 1757584800,
            "time_ms": 1757584800123,
            "channel": "spot.candlesticks",
            "event": "update",
            "result": {
                "t": "1757583900",
                "v": "12.5",
                "c": "114000.5",
                "h": "114100.0",
                "l": "113900.0",
                "o": "113950.0",
                "n": "15m_BTC_USDT",
            },
        }
    )

    event = source._parse_message(message)

    assert event is not None
    assert event.provider == "gateio"
    assert event.sequence == 1757584800123
    assert event.candle.symbol == "BTC/USDT"
    assert event.candle.timeframe == "15m"
    assert event.candle.close == Decimal("114000.5")
    assert event.server_time_ms == 1757584800123
    assert source.clock_snapshot().samples == 1


def test_gateio_websocket_ignores_unsubscribed_candles() -> None:
    source = GateIOWebSocketCandleSource(
        (
            GateIOCandleSubscription(
                canonical_symbol="BTC/USDT",
                provider_symbol="BTC_USDT",
                timeframe="15m",
            ),
        )
    )
    message = json.dumps(
        {
            "time_ms": 1757584800123,
            "channel": "spot.candlesticks",
            "event": "update",
            "result": {
                "t": "1757583900",
                "v": "1",
                "c": "1",
                "h": "1",
                "l": "1",
                "o": "1",
                "n": "1h_ETH_USDT",
            },
        }
    )

    assert source._parse_message(message) is None


def test_candle_stream_ingestor_blocks_duplicates_and_out_of_order() -> None:
    accepted: list[CandleStreamEvent] = []
    ingestor = CandleStreamIngestor(accepted.append)
    candle = Candle(
        symbol="BTC/USDT",
        timeframe="15m",
        timestamp=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("10"),
    )
    first = CandleStreamEvent(
        provider="gateio",
        event_id="event-1",
        sequence=2,
        candle=candle,
        received_at=datetime.now(timezone.utc),
    )
    duplicate = first
    older = CandleStreamEvent(
        provider="gateio",
        event_id="event-2",
        sequence=1,
        candle=candle,
        received_at=datetime.now(timezone.utc),
    )

    assert ingestor.ingest(first) is True
    assert ingestor.ingest(duplicate) is False
    assert ingestor.ingest(older) is False
    assert ingestor.snapshot().accepted == 1
    assert ingestor.snapshot().duplicates == 1
    assert ingestor.snapshot().out_of_order == 1


def test_direct_stream_candle_updates_cache_and_history() -> None:
    history = InMemoryCandleStore()
    cache = MarketDataCache()
    platform = ProductionMarketDataPlatform(
        router=ProviderRouter((FakeProvider(),)),
        cache=cache,
        history=history,
    )
    candle = Candle(
        symbol="BTC/USDT",
        timeframe="15m",
        timestamp=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("10"),
    )
    event = CandleStreamEvent(
        provider="gateio",
        event_id="event-1",
        sequence=1,
        candle=candle,
        received_at=datetime.now(timezone.utc),
    )

    platform.ingest_candle(event)

    assert cache.get_candles("BTC/USDT", "15m") == [candle]
    assert history.load("BTC/USDT", "15m") == [candle]
