from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.data.cache import MarketDataCache
from app.data.candle_builder import CandleBuilder, timeframe_seconds
from app.data.historical_store import SQLiteCandleStore
from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.platform import ProductionMarketDataPlatform
from app.data.provider_router import ProviderRouter
from app.data.sla import DataSLA, MarketDataSLAMonitor, SLAStatus
from app.data.streaming import MarketDataStreamIngestor, TradeEvent
from app.universe.discovery import DynamicUniverseDiscovery
from app.universe.instrument import AssetClass, Instrument


class DiscoveryProvider:
    name = "venue-a"

    def discover_instruments(self):
        return (
            Instrument("BTCUSDT", AssetClass.CRYPTO, "BTC", "USDT"),
            Instrument("OLDUSDT", AssetClass.CRYPTO, "OLD", "USDT", tradable=False),
        )


class FailingDiscoveryProvider:
    name = "venue-down"

    def discover_instruments(self):
        raise RuntimeError("metadata unavailable")


class FakeMarketProvider:
    name = "fake"

    def __init__(self, now):
        self.now = now
        self.live_calls = 0
        self.candle_calls = 0

    def get_live_price(self, symbol):
        self.live_calls += 1
        return LivePrice(symbol, Decimal("100"), self.now, self.name)

    def get_candles(self, request):
        self.candle_calls += 1
        assert request.timeframe is not None
        start = self.now - timedelta(minutes=15 * (request.limit - 1))
        return [
            Candle(
                symbol=request.symbol,
                timeframe=request.timeframe,
                timestamp=start + timedelta(minutes=15 * index),
                open=Decimal("100"),
                high=Decimal("102"),
                low=Decimal("99"),
                close=Decimal("101"),
                volume=Decimal("10"),
            )
            for index in range(request.limit)
        ]


def make_trade(sequence, minute, price="100", event_id=None):
    return TradeEvent(
        provider="stream",
        symbol="BTCUSDT",
        event_id=event_id or f"event-{sequence}",
        sequence=sequence,
        price=Decimal(price),
        quantity=Decimal("2"),
        timestamp=datetime(2026, 9, 11, 8, minute, tzinfo=timezone.utc),
    )


def test_dynamic_universe_discovery_reports_provider_failure():
    service = DynamicUniverseDiscovery((DiscoveryProvider(), FailingDiscoveryProvider()))
    result = service.discover()

    assert [item.symbol for item in result.instruments] == ["BTCUSDT"]
    assert result.providers == ("venue-a",)
    assert result.errors == ("venue-down: metadata unavailable",)
    assert not result.healthy
    assert result.build_registry().get("btcusdt").base_asset == "BTC"


def test_stream_ingestor_rejects_duplicates_and_out_of_order_events():
    accepted = []
    ingestor = MarketDataStreamIngestor(accepted.append)

    assert ingestor.ingest(make_trade(1, 0))
    assert not ingestor.ingest(make_trade(2, 1, event_id="event-1"))
    assert not ingestor.ingest(make_trade(1, 2, event_id="late"))

    snapshot = ingestor.snapshot()
    assert len(accepted) == 1
    assert snapshot.accepted == 1
    assert snapshot.duplicates == 1
    assert snapshot.out_of_order == 1


def test_candle_builder_closes_previous_bucket():
    builder = CandleBuilder("15m")
    assert builder.add_trade(make_trade(1, 1, "100")) is None
    assert builder.add_trade(make_trade(2, 5, "105")) is None
    closed = builder.add_trade(make_trade(3, 16, "103"))

    assert closed is not None
    assert closed.open == Decimal("100")
    assert closed.high == Decimal("105")
    assert closed.low == Decimal("100")
    assert closed.close == Decimal("105")
    assert closed.volume == Decimal("4")
    assert timeframe_seconds("4h") == 14400


def test_cache_enforces_live_freshness_and_candle_limit():
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    cache = MarketDataCache(max_candles_per_series=2)
    cache.put_live_price(LivePrice("BTCUSDT", Decimal("100"), now, "test"))

    assert cache.get_live_price("BTCUSDT", max_age_seconds=30, now=now) is not None
    assert (
        cache.get_live_price(
            "BTCUSDT", max_age_seconds=30, now=now + timedelta(seconds=31)
        )
        is None
    )

    candles = [
        Candle(
            "BTCUSDT",
            "15m",
            now + timedelta(minutes=15 * index),
            Decimal("1"),
            Decimal("2"),
            Decimal("1"),
            Decimal("2"),
            Decimal("10"),
        )
        for index in range(3)
    ]
    cache.put_candles(candles)
    assert len(cache.get_candles("BTCUSDT", "15m")) == 2


def test_sqlite_history_is_idempotent(tmp_path):
    store = SQLiteCandleStore(tmp_path / "market_data.db")
    candle = Candle(
        "BTCUSDT",
        "15m",
        datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc),
        Decimal("100"),
        Decimal("102"),
        Decimal("99"),
        Decimal("101"),
        Decimal("20"),
    )
    store.upsert([candle, candle])

    loaded = store.load("BTCUSDT", "15m", limit=10)
    assert loaded == [candle]


def test_sla_monitor_reports_healthy_degraded_and_stale():
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    monitor = MarketDataSLAMonitor(DataSLA(max_live_age_seconds=100, degraded_ratio=0.75))

    healthy = monitor.evaluate_live(
        LivePrice("BTCUSDT", Decimal("100"), now - timedelta(seconds=10), "x"),
        now=now,
    )
    degraded = monitor.evaluate_live(
        LivePrice("BTCUSDT", Decimal("100"), now - timedelta(seconds=80), "x"),
        now=now,
    )
    stale = monitor.evaluate_live(
        LivePrice("BTCUSDT", Decimal("100"), now - timedelta(seconds=101), "x"),
        now=now,
    )

    assert healthy.status is SLAStatus.HEALTHY
    assert degraded.status is SLAStatus.DEGRADED
    assert degraded.usable
    assert stale.status is SLAStatus.STALE
    assert not stale.usable


def test_platform_uses_router_then_cache_and_history(tmp_path):
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    provider = FakeMarketProvider(now)
    router = ProviderRouter((provider,), max_live_age_seconds=30)
    cache = MarketDataCache()
    history = SQLiteCandleStore(tmp_path / "platform.db")
    platform = ProductionMarketDataPlatform(
        router=router,
        cache=cache,
        history=history,
        timeframes=("15m",),
    )

    first = platform.get_live_price("BTCUSDT", now=now)
    second = platform.get_live_price("BTCUSDT", now=now)
    assert first == second
    assert provider.live_calls == 1

    request = MarketDataRequest("BTCUSDT", "15m", limit=2)
    candles = platform.get_candles(request, max_age_seconds=1800, now=now)
    assert len(candles) == 2
    assert provider.candle_calls == 1
    assert len(history.load("BTCUSDT", "15m", limit=10)) == 2


def test_platform_stream_ingest_closes_and_persists_candle(tmp_path):
    now = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    provider = FakeMarketProvider(now)
    cache = MarketDataCache()
    history = SQLiteCandleStore(tmp_path / "stream.db")
    platform = ProductionMarketDataPlatform(
        router=ProviderRouter((provider,)),
        cache=cache,
        history=history,
        timeframes=("15m",),
    )

    assert platform.ingest_trade(make_trade(1, 1, "100")) == ()
    closed = platform.ingest_trade(make_trade(2, 16, "101"))

    assert len(closed) == 1
    assert cache.get_live_price("BTCUSDT") is not None
    assert history.load("BTCUSDT", "15m", limit=10) == list(closed)
