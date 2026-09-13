from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.data.adaptive_failover import AdaptiveSourceHealth
from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.data.source_benchmark import SourceBenchmark
from app.data.source_registry import SourceMapping, SourceMappingRegistry, SourceRoute


class FixtureProvider(MarketDataProvider):
    def __init__(self, name: str, *, volume: Decimal = Decimal("1")) -> None:
        self.name = name
        self.volume = volume

    def get_live_price(self, symbol: str) -> LivePrice:
        return LivePrice(symbol, Decimal("100"), datetime.now(timezone.utc), self.name)

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        return [Candle(
            request.symbol, request.timeframe or "1h", datetime.now(timezone.utc),
            Decimal("99"), Decimal("101"), Decimal("98"), Decimal("100"), self.volume,
        ) for _ in range(request.limit)]


def test_source_benchmark_qualifies_complete_low_latency_route() -> None:
    registry = SourceMappingRegistry((SourceMapping(
        "TEST", "equity", (SourceRoute("fixture", "TEST", max_latency_seconds=Decimal("5")),),
        minimum_candles=2,
    ),))
    results = SourceBenchmark(
        registry, {"fixture": FixtureProvider("fixture")},
        timeframes=("1d",), candle_limit=2, max_workers=1,
    ).run({"TEST": Decimal("100")})

    assert len(results) == 1
    assert results[0].qualified
    assert results[0].candle_counts == {"1d": 2}
    assert results[0].average_request_latency_seconds <= Decimal("5")


def test_adaptive_health_opens_circuit_after_repeated_failures() -> None:
    health = AdaptiveSourceHealth(failure_threshold=2, cooldown_seconds=300)

    health.failure("yahoo", "EURUSD=X", RuntimeError("first"))
    assert health.available("yahoo", "EURUSD=X")
    health.failure("yahoo", "EURUSD=X", RuntimeError("second"))
    assert not health.available("yahoo", "EURUSD=X")
    health.success("yahoo", "EURUSD=X")
    assert health.available("yahoo", "EURUSD=X")
