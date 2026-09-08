from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.data.market_data import Candle, LivePrice
from app.data.quality import validate_candles, validate_live_price


def test_stale_live_price_is_rejected():
    price = LivePrice(
        symbol="BTC/USDT",
        price=Decimal("70000"),
        as_of=datetime.now(timezone.utc) - timedelta(minutes=3),
        provider="test",
    )
    result = validate_live_price(price)
    assert not result.valid
    assert "live price is stale" in result.reasons


def test_invalid_candle_ohlc_is_rejected():
    candle = Candle(
        symbol="BTC/USDT",
        timeframe="1h",
        timestamp=datetime.now(timezone.utc),
        open=Decimal("110"),
        high=Decimal("100"),
        low=Decimal("90"),
        close=Decimal("95"),
        volume=Decimal("1"),
    )
    result = validate_candles((candle,))
    assert not result.valid
    assert any("high below low" in reason for reason in result.reasons)
