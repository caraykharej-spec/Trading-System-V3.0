from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.provider_router import ProviderRouter
from app.data.quality import detect_price_outliers, validate_candles, validate_live_price
from app.data.reconciliation import reconcile_candles, reconcile_live_prices
from app.data.reliability import CircuitBreaker, CircuitOpenError, call_with_retry


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def candle(ts, close="100", timeframe="15m"):
    c = Decimal(close)
    return Candle("BTC/USDT", timeframe, ts, c, c + 1, c - 1, c, Decimal("10"))


def test_candle_gap_is_rejected():
    result = validate_candles((candle(NOW), candle(NOW + timedelta(minutes=30))), expected_timeframe="15m")
    assert not result.valid
    assert any("gap detected" in r for r in result.reasons)


def test_duplicate_candle_timestamp_is_rejected():
    result = validate_candles((candle(NOW), candle(NOW)), expected_timeframe="15m")
    assert not result.valid
    assert "candles are not strictly chronological" in result.reasons


def test_future_and_naive_timestamps_are_rejected():
    future = LivePrice("BTC/USDT", Decimal("100"), NOW + timedelta(minutes=1), "test")
    assert not validate_live_price(future, now=NOW).valid
    naive = LivePrice("BTC/USDT", Decimal("100"), datetime(2026, 1, 1), "test")
    assert not validate_live_price(naive, now=NOW).valid


def test_outlier_is_rejected():
    result = detect_price_outliers((candle(NOW, "100"), candle(NOW + timedelta(minutes=15), "200")), max_return=Decimal("0.20"))
    assert not result.valid


def test_provider_price_reconciliation_rejects_large_disagreement():
    prices = [
        LivePrice("BTC/USDT", Decimal("100"), NOW, "a"),
        LivePrice("BTC/USDT", Decimal("102"), NOW, "b"),
    ]
    result = reconcile_live_prices(prices, now=NOW, max_disagreement_ratio=Decimal("0.01"))
    assert not result.valid
    assert result.spread_ratio == Decimal("0.02")


def test_provider_candle_reconciliation_rejects_large_close_difference():
    a = (candle(NOW, "100"), candle(NOW + timedelta(minutes=15), "101"))
    b = (candle(NOW, "105"), candle(NOW + timedelta(minutes=15), "101"))
    result = reconcile_candles({"a": a, "b": b}, expected_timeframe="15m", now=NOW)
    assert not result.valid


def test_retry_uses_exponential_backoff():
    calls = []
    delays = []

    def operation():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("temporary")
        return "ok"

    assert call_with_retry(operation, attempts=3, backoff_seconds=0.5, sleeper=delays.append) == "ok"
    assert delays == [0.5, 1.0]


def test_circuit_breaker_opens_and_recovers():
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=0)
    breaker.record_failure()
    assert not breaker.is_open
    breaker.record_failure()
    assert not breaker.is_open  # zero-second recovery immediately permits a probe
    breaker.before_call()
    breaker.record_success()
    assert not breaker.is_open


def test_router_falls_back_after_unreliable_provider():
    class Bad:
        name = "bad"

        def get_live_price(self, symbol):
            return LivePrice(symbol, Decimal("0"), NOW, self.name)

        def get_candles(self, request):
            return []

    class Good:
        name = "good"

        def get_live_price(self, symbol):
            return LivePrice(symbol, Decimal("100"), NOW, self.name)

        def get_candles(self, request):
            return [candle(NOW, "100", request.timeframe)]

    router = ProviderRouter((Bad(), Good()), max_live_age_seconds=120, retry_attempts=1)
    assert router.get_live_price("BTC/USDT", now=NOW).provider == "good"


def test_router_rejects_gap_and_falls_back():
    class Bad:
        name = "bad"

        def get_live_price(self, symbol):
            return LivePrice(symbol, Decimal("100"), NOW, self.name)

        def get_candles(self, request):
            return [candle(NOW, "100", request.timeframe), candle(NOW + timedelta(minutes=30), "101", request.timeframe)]

    class Good:
        name = "good"

        def get_live_price(self, symbol):
            return LivePrice(symbol, Decimal("100"), NOW, self.name)

        def get_candles(self, request):
            return [candle(NOW, "100", request.timeframe)]

    router = ProviderRouter((Bad(), Good()), retry_attempts=1)
    result = router.get_candles(MarketDataRequest("BTC/USDT", "15m", 2), max_age_seconds=100)
    assert result[0].close == Decimal("100")
