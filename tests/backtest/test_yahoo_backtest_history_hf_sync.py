from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from scripts.backtest import sync_yahoo_backtest_history_to_hf as subject
from scripts.backtest import sync_yahoo_history_to_hf as legacy


def _candle(timestamp: datetime) -> legacy.YahooCandle:
    return legacy.YahooCandle(
        timestamp=timestamp,
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        adjusted_close=Decimal("1"),
        volume=Decimal("1"),
    )


def _partition(route, timeframe, year, rows, force):
    return legacy.YahooPartition(
        timeframe=timeframe,
        year=year,
        rows=len(rows),
        object_key=f"{timeframe}/{year}",
        sha256="abc",
        first_timestamp=rows[0].timestamp.isoformat(),
        last_timestamp=rows[-1].timestamp.isoformat(),
        reused_verified=True,
    )


def test_sync_uses_distinct_15m_hourly_and_daily_windows(monkeypatch) -> None:
    end = datetime(2026, 9, 16, tzinfo=timezone.utc)
    route = legacy.YahooRoute(
        canonical_symbol="AAPL",
        base_asset="AAPL",
        asset_class="equity",
        provider_symbol="AAPL",
    )
    calls: list[tuple[str, datetime, datetime]] = []

    def fake_fetch(route_arg, interval, *, start, end, quality=None):
        assert route_arg == route
        calls.append((interval, start, end))
        if quality is not None:
            quality.setdefault("ohlc_invariant_rows_dropped", 0)
        return [_candle(end - timedelta(hours=1)), _candle(end)]

    monkeypatch.setattr(legacy, "fetch_history", fake_fetch)
    monkeypatch.setattr(legacy, "aggregate_four_hour", lambda rows: list(rows))
    monkeypatch.setattr(legacy, "_store_partition", _partition)
    monkeypatch.setattr(legacy, "_put_json", lambda payload, key: None)

    payload = subject.sync_route(route, end=end)

    starts = {interval: start for interval, start, _ in calls}
    assert starts["15m"] == end - timedelta(days=59)
    assert starts["1h"] == end - timedelta(days=729)
    assert starts["1d"] == end - timedelta(days=36_159)
    assert payload["history_policy"] == {
        "15m": "last_59_days",
        "1h": "last_729_days",
        "4h": "derived_from_last_729_days_of_1h",
        "1d": "explicit_last_36159_days",
    }
    assert payload["daily_derived_from_hourly_due_to_empty_valid_source"] is False
    assert (
        payload["coverage"]["1d"][
            "derived_from_hourly_due_to_empty_valid_daily_source"
        ]
        is False
    )


def test_sync_derives_daily_from_hourly_when_native_daily_is_empty(monkeypatch) -> None:
    end = datetime(2026, 9, 16, tzinfo=timezone.utc)
    route = legacy.YahooRoute(
        canonical_symbol="TON",
        base_asset="TON",
        asset_class="crypto",
        provider_symbol="TON11419-USD",
    )
    hourly = [_candle(end - timedelta(days=2)), _candle(end - timedelta(days=1))]
    derived_daily = [_candle(end - timedelta(days=2)), _candle(end - timedelta(days=1))]
    aggregate_daily_calls: list[list[legacy.YahooCandle]] = []

    def fake_fetch(route_arg, interval, *, start, end, quality=None):
        assert route_arg == route
        if quality is not None:
            quality.setdefault("ohlc_invariant_rows_dropped", 0)
        if interval == "1d":
            return []
        if interval == "1h":
            return list(hourly)
        return [_candle(end - timedelta(hours=1)), _candle(end)]

    def fake_daily(rows):
        aggregate_daily_calls.append(list(rows))
        return list(derived_daily)

    monkeypatch.setattr(legacy, "fetch_history", fake_fetch)
    monkeypatch.setattr(legacy, "aggregate_four_hour", lambda rows: list(rows))
    monkeypatch.setattr(legacy, "aggregate_daily", fake_daily)
    monkeypatch.setattr(legacy, "_store_partition", _partition)
    monkeypatch.setattr(legacy, "_put_json", lambda payload, key: None)

    payload = subject.sync_route(route, end=end)

    assert payload["status"] == "COMPLETE"
    assert aggregate_daily_calls == [hourly]
    assert payload["daily_derived_from_hourly_due_to_empty_valid_source"] is True
    assert payload["history_policy"]["1d"] == (
        "derived_from_last_729_days_of_1h_due_to_empty_valid_daily_source"
    )
    assert (
        payload["coverage"]["1d"][
            "derived_from_hourly_due_to_empty_valid_daily_source"
        ]
        is True
    )


def test_main_installs_shared_hf_transport(monkeypatch, tmp_path) -> None:
    output = tmp_path / "discovery.json"
    monkeypatch.setattr(subject, "discover_routes", lambda: [])
    monkeypatch.setattr(
        subject.argparse.ArgumentParser,
        "parse_args",
        lambda self: subject.argparse.Namespace(
            discover_only=True,
            canonical=None,
            base_asset=None,
            asset_class="unknown",
            provider_symbol=None,
            price_multiplier="1",
            requires_volume=True,
            end=None,
            force=False,
            output=str(output),
        ),
    )

    subject.main()

    assert legacy._aws is subject.hf_s3.aws
