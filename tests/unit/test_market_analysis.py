from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.data.market_data import Candle
from app.market.analysis import analyze_market


def make_candles(n=220):
    start = datetime.now(timezone.utc) - timedelta(hours=n)
    result = []
    for i in range(n):
        close = Decimal("100") + Decimal(i) / Decimal("10")
        result.append(Candle(symbol="TEST/USDT", timeframe="1h", timestamp=start + timedelta(hours=i), open=close - Decimal("0.2"), high=close + Decimal("0.5"), low=close - Decimal("0.5"), close=close, volume=Decimal("1000")))
    return result


def test_market_snapshot_is_deterministic():
    snapshot = analyze_market("TEST/USDT", "1h", make_candles())
    assert snapshot.trend.direction == "BULLISH"
    assert snapshot.indicators.ema200 is not None
    assert snapshot.liquidity.volume_ratio == Decimal("1")
    assert snapshot.advanced_structure.trend in {"BULLISH", "TRANSITION", "UNKNOWN"}
    assert Decimal("0") <= snapshot.score <= Decimal("100")
