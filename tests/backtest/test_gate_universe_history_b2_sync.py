from datetime import datetime, timezone
from decimal import Decimal

from app.data.market_data import Candle
from scripts.backtest.sync_gate_universe_history_to_b2 import (
    GateHistoryRoute,
    iter_month_ranges,
    resample,
)
from scripts.backtest.sync_gate_universe_monthly_archive_to_b2 import archive_month_url


def _candle(minute: int, close: str) -> Candle:
    value = Decimal(close)
    return Candle(
        symbol="BTC/USDT",
        timeframe="5m",
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


def test_resample_builds_complete_one_hour_bar_from_five_minute_source() -> None:
    candles = [_candle(index * 5, str(100 + index)) for index in range(12)]

    rows = resample(candles, "1h")

    assert len(rows) == 1
    bar = rows[0]
    assert bar.open == Decimal("100")
    assert bar.high == Decimal("112")
    assert bar.low == Decimal("99")
    assert bar.close == Decimal("111")
    assert bar.volume == Decimal("120")


def test_resample_builds_complete_fifteen_minute_bar() -> None:
    rows = resample(
        [_candle(0, "100"), _candle(5, "101"), _candle(10, "102")],
        "15m",
    )

    assert len(rows) == 1
    assert rows[0].open == Decimal("100")
    assert rows[0].close == Decimal("102")


def test_resample_drops_incomplete_higher_timeframe_bar() -> None:
    rows = resample(
        [_candle(0, "100"), _candle(5, "101"), _candle(15, "102")],
        "15m",
    )

    assert rows == []


def test_archive_url_uses_production_spot_monthly_kline_layout() -> None:
    route = GateHistoryRoute(
        canonical_symbol="BTC/USDT",
        base_asset="BTC",
        asset_class="crypto",
        provider="gateio",
        provider_symbol="BTC_USDT",
    )

    assert archive_month_url(route, datetime(2026, 9, 13, tzinfo=timezone.utc)) == (
        "https://download.gatedata.org/spot/candlesticks_5m/202609/"
        "BTC_USDT-202609.csv.gz"
    )


def test_archive_url_uses_production_usdt_futures_monthly_layout() -> None:
    route = GateHistoryRoute(
        canonical_symbol="1000PEPE/USDT",
        base_asset="1000PEPE",
        asset_class="crypto",
        provider="gateio_futures",
        provider_symbol="PEPE_USDT",
        price_multiplier="1000",
    )

    assert archive_month_url(route, datetime(2026, 9, 13, tzinfo=timezone.utc)) == (
        "https://download.gatedata.org/futures_usdt/candlesticks_5m/202609/"
        "PEPE_USDT-202609.csv.gz"
    )


def test_tradfi_route_is_explicitly_not_full_history_capable() -> None:
    route = GateHistoryRoute(
        canonical_symbol="AAPL/USDT",
        base_asset="AAPL",
        asset_class="equity",
        provider="gateio_tradfi",
        provider_symbol="AAPL",
    )

    assert route.full_history_supported is False
