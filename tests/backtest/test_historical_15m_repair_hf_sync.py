from __future__ import annotations

import json
import lzma
import struct
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from app.data.historical_15m_registry import Historical15mRegistry
from scripts.backtest import sync_historical_15m_repair_to_hf as subject


def _candle(timestamp: datetime, value: str = "100") -> subject.Candle:
    price = Decimal(value)
    return subject.Candle(timestamp, price, price + 1, price - 1, price, Decimal("1"))


def test_registry_is_the_26_non_crypto_yahoo_intraday_repairs() -> None:
    routes = Historical15mRegistry.load().all()
    counts: dict[str, int] = {}
    for route in routes:
        counts[route.asset_class] = counts.get(route.asset_class, 0) + 1

    assert len(routes) == 26
    assert counts == {"commodity": 3, "equity": 16, "forex": 6, "index": 1}
    assert {route.provider for route in routes} == {"alpaca_sip", "dukascopy"}
    assert Historical15mRegistry.load().get("NFLX").price_multiplier == Decimal("10")
    assert Historical15mRegistry.load().get("SPX").proxy_for == "SPX"


def test_parse_dukascopy_bi5_and_apply_reviewed_scale() -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    record = struct.pack(">5If", 60, 110000, 110020, 109990, 110010, 12.5)
    quality = {
        "invalid_rows_dropped": 0,
        "ohlc_invariant_rows_dropped": 0,
        "out_of_session_rows_dropped": 0,
        "source_days_without_rows": 0,
    }

    rows = subject.parse_dukascopy_day(
        lzma.compress(record), route, date(2026, 9, 1), quality=quality
    )

    assert len(rows) == 1
    assert rows[0].timestamp == datetime(2026, 9, 1, 0, 1, tzinfo=timezone.utc)
    assert rows[0].open == Decimal("1.10000")
    assert rows[0].high == Decimal("1.10020")
    assert rows[0].low == Decimal("1.09990")
    assert rows[0].close == Decimal("1.10010")


def test_alpaca_is_fail_closed_to_sip_and_filters_extended_hours(monkeypatch) -> None:
    route = Historical15mRegistry.load().get("AAPL")
    assert route is not None
    observed: list[str] = []

    def fake_request(url: str, *, attempts: int = 6):
        observed.append(url)
        return {
            "bars": [
                {"t": "2026-09-01T13:15:00Z", "o": 10, "h": 11, "l": 9, "c": 10, "v": 1},
                {"t": "2026-09-01T13:30:00Z", "o": 10, "h": 11, "l": 9, "c": 10, "v": 2},
            ],
            "next_page_token": None,
        }

    monkeypatch.setattr(subject, "_request_alpaca_json", fake_request)
    quality = {
        "invalid_rows_dropped": 0,
        "ohlc_invariant_rows_dropped": 0,
        "out_of_session_rows_dropped": 0,
        "source_days_without_rows": 0,
    }
    rows = subject.fetch_alpaca_15m(
        route,
        start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        end=datetime(2026, 9, 2, tzinfo=timezone.utc),
        quality=quality,
    )

    query = parse_qs(urlparse(observed[0]).query)
    assert query["feed"] == ["sip"]
    assert query["adjustment"] == ["all"]
    assert [row.timestamp for row in rows] == [
        datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)
    ]
    assert quality["out_of_session_rows_dropped"] == 1


def test_us_equity_hourly_buckets_are_anchored_to_rth_open() -> None:
    rows = [
        _candle(datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc), "100"),
        _candle(datetime(2026, 9, 1, 14, 15, tzinfo=timezone.utc), "101"),
        _candle(datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc), "102"),
    ]

    hourly = subject.aggregate_candles(rows, "1h", session="us_rth")

    assert [row.timestamp for row in hourly] == [
        datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc),
        datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc),
    ]
    assert hourly[0].open == Decimal("100")
    assert hourly[0].close == Decimal("101")


def test_sync_builds_all_required_timeframes_without_network_or_storage(monkeypatch) -> None:
    route = Historical15mRegistry.load().get("AAPL")
    assert route is not None
    route = replace(route, minimum_history_days=0)
    start = datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)
    fifteen = [_candle(start + timedelta(minutes=15 * index)) for index in range(32)]
    stored: list[tuple[str, int, int]] = []

    monkeypatch.setattr(
        subject,
        "fetch_alpaca_15m",
        lambda route, *, start, end, quality: list(fifteen),
    )

    def fake_store(route, timeframe, year, rows, *, force):
        stored.append((timeframe, year, len(rows)))
        return subject.Partition(
            timeframe=timeframe,
            year=year,
            rows=len(rows),
            object_key=f"{timeframe}/{year}",
            sha256="a" * 64,
            first_timestamp=rows[0].timestamp.isoformat(),
            last_timestamp=rows[-1].timestamp.isoformat(),
            reused_verified=True,
        )

    monkeypatch.setattr(subject, "_store_partition", fake_store)
    monkeypatch.setattr(subject.storage, "_put_json", lambda payload, key: None)

    payload = subject.sync_route(
        route,
        start=start,
        end=start + timedelta(hours=8),
    )

    assert payload["status"] == "COMPLETE"
    assert set(payload["coverage"]) == {"15m", "1h", "4h", "1d"}
    assert payload["qualification_scope"] == "research_backtest_only_live_route_order_unchanged"
    assert {item[0] for item in stored} == {"15m", "1h", "4h", "1d"}


def test_discovery_payload_is_json_serializable(tmp_path, monkeypatch) -> None:
    output = tmp_path / "discovery.json"
    monkeypatch.setattr(
        subject.argparse.ArgumentParser,
        "parse_args",
        lambda self: subject.argparse.Namespace(
            discover_only=True,
            base_asset=None,
            start=None,
            end=None,
            force=False,
            output=str(output),
        ),
    )

    assert subject.main() == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["route_count"] == 26
