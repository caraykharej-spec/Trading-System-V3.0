from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from scripts.backtest import sync_yahoo_history_to_hf as subject


def _route() -> subject.YahooRoute:
    return subject.YahooRoute("TEST", "TEST", "equity", "TEST", "10", True)


def test_discovery_contains_every_explicit_yahoo_route_once() -> None:
    routes = subject.discover_routes()
    expected = {
        (mapping.base_asset, route.symbol.upper())
        for mapping in subject.SourceMappingRegistry.load().all()
        for route in mapping.routes
        if route.provider == "yahoo"
    }
    assert {(route.base_asset, route.provider_symbol.upper()) for route in routes} == expected


def test_parse_chart_preserves_raw_and_adjusted_values() -> None:
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "timestamp": [1_700_000_000],
                    "indicators": {
                        "quote": [
                            {"open": [1], "high": [3], "low": [0.5], "close": [2], "volume": [7]}
                        ],
                        "adjclose": [{"adjclose": [1.5]}],
                    },
                }
            ],
        }
    }
    rows = subject.parse_chart(payload, _route())
    assert len(rows) == 1
    assert rows[0].open == Decimal("10")
    assert rows[0].close == Decimal("20")
    assert rows[0].adjusted_close == Decimal("15.0")
    assert rows[0].volume == Decimal("7")


def test_parse_chart_drops_and_records_source_ohlc_invariant_violation() -> None:
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "timestamp": [1_704_067_200, 1_704_153_600],
                    "indicators": {
                        "quote": [
                            {
                                "open": [1.1055831909179688, 1.10],
                                "high": [1.1053388118743896, 1.11],
                                "low": [1.1039965152740479, 1.09],
                                "close": [1.1055831909179688, 1.105],
                                "volume": [0, 0],
                            }
                        ],
                        "adjclose": [{"adjclose": [1.1055831909179688, 1.105]}],
                    },
                }
            ],
        }
    }
    quality: dict[str, int] = {}

    rows = subject.parse_chart(payload, _route(), quality=quality)

    assert len(rows) == 1
    assert rows[0].close == Decimal("11.050")
    assert quality == {"ohlc_invariant_rows_dropped": 1}


def test_four_hour_aggregation_is_utc_aligned() -> None:
    rows = [
        subject.YahooCandle(
            datetime(2026, 1, 1, hour, tzinfo=timezone.utc),
            Decimal(str(hour + 1)),
            Decimal("10"),
            Decimal("0.5"),
            Decimal(str(hour + 2)),
            Decimal(str(hour + 2)),
            Decimal("1"),
        )
        for hour in range(4)
    ]
    aggregated = subject.aggregate_four_hour(rows)
    assert len(aggregated) == 1
    assert aggregated[0].timestamp == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert aggregated[0].open == Decimal("1")
    assert aggregated[0].close == Decimal("5")
    assert aggregated[0].volume == Decimal("4")


def test_daily_aggregation_is_utc_aligned_and_preserves_bounds() -> None:
    rows = [
        subject.YahooCandle(
            datetime(2026, 1, 1, hour, tzinfo=timezone.utc),
            Decimal(str(hour + 2)),
            Decimal(str(hour + 5)),
            Decimal(str(hour + 1)),
            Decimal(str(hour + 3)),
            Decimal(str(hour + 3)),
            Decimal("2"),
        )
        for hour in (0, 12)
    ]

    aggregated = subject.aggregate_daily(rows)

    assert len(aggregated) == 1
    assert aggregated[0].timestamp == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert aggregated[0].open == Decimal("2")
    assert aggregated[0].high == Decimal("17")
    assert aggregated[0].low == Decimal("1")
    assert aggregated[0].close == Decimal("15")
    assert aggregated[0].volume == Decimal("4")


def test_partition_key_is_year_bounded_and_sanitized() -> None:
    route = subject.YahooRoute("SPX", "SPX", "index", "^GSPC")
    assert subject._partition_key(route, "1d", 2026) == (
        "bronze/yahoo-history/v1/canonical=SPX/market=GSPC/timeframe=1d/year=2026/part-000.parquet"
    )
