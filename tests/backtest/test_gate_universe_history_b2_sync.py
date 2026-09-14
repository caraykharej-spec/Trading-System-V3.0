from datetime import datetime, timezone
from decimal import Decimal

from app.data.market_data import Candle
from scripts.backtest.sync_gate_universe_history_to_b2 import (
    GateHistoryRoute,
    iter_month_ranges,
    resample,
)


def _candle(minute: int, close: str) -> Candle:
    value = Decimal(close)
    return Candle(
        symbol="BTC/USDT",
        timeframe="15m",
        timestamp=datetime(2026, 1, 1, 0, minute, tzinfo=timezone.utc),
        open=value,
        high=value + Decimal("1"),
        low=value - Decimal("1"),
        close=value,
        volume=Decimal("10"),
    )


def test_iter_month_ranges_clips_first_and_last_month() -> None:
    start = datetime(2025, 12, 15, tzinfo=timezone.utc)
    end = datetime(2026, 2, 10, tzinfo=timezone.utc)

    ranges = list(iter_month_ranges(start, end))

    assert ranges == [
        (
            datetime(2025, 12, 15, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 2, 1, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            datetime(2026, 2, 10, tzinfo=timezone.utc),
        ),
    ]


def test_resample_builds_complete_one_hour_bar() -> None:
    candles = [
        _candle(0, "100"),
        _candle(15, "101"),
        _candle(30, "99"),
        _candle(45, "102"),
    ]

    rows = resample(candles, "1h")

    assert len(rows) == 1
    bar = rows[0]
    assert bar.open == Decimal("100")
    assert bar.high == Decimal("103")
    assert bar.low == Decimal("98")
    assert bar.close == Decimal("102")
    assert bar.volume == Decimal("40")


def test_resample_drops_incomplete_higher_timeframe_bar() -> None:
    rows = resample(
        [_candle(0, "100"), _candle(15, "101"), _candle(45, "102")],
        "1h",
    )

    assert rows == []


def test_tradfi_route_is_explicitly_not_full_history_capable() -> None:
    route = GateHistoryRoute(
        canonical_symbol="AAPL/USDT",
        base_asset="AAPL",
        asset_class="equity",
        provider="gateio_tradfi",
        provider_symbol="AAPL",
    )

    assert route.full_history_supported is False
