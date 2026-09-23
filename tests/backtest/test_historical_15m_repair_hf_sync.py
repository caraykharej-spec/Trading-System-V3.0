from __future__ import annotations

import json
import lzma
import struct
import urllib.error
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email.message import Message
from urllib.parse import parse_qs, urlparse

import pytest

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


class _ByteResponse:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def _http_error(status: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://example.test/file.bi5", status, "failure", headers, None)


def test_dukascopy_503_retries_with_retry_after_backoff_and_jitter(monkeypatch) -> None:
    responses = iter(
        [
            _http_error(503, "5"),
            _http_error(503),
            _ByteResponse(b"payload"),
        ]
    )
    calls = 0
    sleeps: list[float] = []

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        result = next(responses)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(subject.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(subject.time, "sleep", sleeps.append)
    monkeypatch.setattr(subject.random, "uniform", lambda start, end: 0.25)

    result = subject._request_bytes("https://example.test/file.bi5", attempts=3)

    assert result == b"payload"
    assert calls == 3
    assert sleeps == [5.25, 4.25]


def test_dukascopy_non_transient_http_error_is_not_retried(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        raise _http_error(403)

    monkeypatch.setattr(subject.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(subject.time, "sleep", sleeps.append)

    with pytest.raises(subject.ProviderError, match="historical data HTTP 403"):
        subject._request_bytes("https://example.test/file.bi5", attempts=7)

    assert calls == 1
    assert sleeps == []


def test_dukascopy_404_remains_an_expected_empty_market_day(monkeypatch) -> None:
    monkeypatch.setattr(
        subject.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(_http_error(404)),
    )
    assert subject._request_bytes("https://example.test/file.bi5", attempts=7) == b""


def test_dukascopy_timeout_retries_then_succeeds(monkeypatch) -> None:
    responses = iter([TimeoutError("timed out"), _ByteResponse(b"payload")])
    sleeps: list[float] = []

    def fake_urlopen(request, timeout):
        result = next(responses)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(subject.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(subject.time, "sleep", sleeps.append)
    monkeypatch.setattr(subject.random, "uniform", lambda start, end: 0.0)

    assert subject._request_bytes("https://example.test/file.bi5", attempts=2) == b"payload"
    assert sleeps == [2.0]


def test_dukascopy_transport_retry_budget_is_independent(monkeypatch) -> None:
    responses = iter([ConnectionResetError("reset"), _ByteResponse(b"payload")])
    monkeypatch.setattr(subject.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(subject.random, "uniform", lambda start, end: 0.0)

    def fake_urlopen(request, timeout):
        result = next(responses)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(subject.urllib.request, "urlopen", fake_urlopen)

    assert (
        subject._request_bytes("https://example.test/file.bi5", attempts=1, transport_attempts=2)
        == b"payload"
    )


def test_dukascopy_failure_reports_exact_source_day(monkeypatch) -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    monkeypatch.setattr(
        subject,
        "_request_bytes",
        lambda url: (_ for _ in ()).throw(subject.ProviderError("historical data request failed")),
    )
    monkeypatch.setattr(subject, "_pace_dukascopy_request", lambda: None)

    with pytest.raises(subject.ProviderError, match=r"EUR/EURUSD failed on 2022-01-01"):
        subject.fetch_dukascopy_15m(
            route,
            start=datetime(2022, 1, 1, tzinfo=timezone.utc),
            end=datetime(2022, 1, 2, tzinfo=timezone.utc),
            quality=subject._empty_quality(),
        )


def test_dukascopy_request_pacing_is_configurable(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setenv("DUKASCOPY_REQUEST_INTERVAL_SECONDS", "0.125")
    monkeypatch.setattr(subject.time, "sleep", sleeps.append)

    subject._pace_dukascopy_request()

    assert sleeps == [0.125]


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
    assert [row.timestamp for row in rows] == [datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)]
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


def _fake_partition(
    timeframe: str, year: int, start: datetime, *, reused: bool
) -> subject.Partition:
    return subject.Partition(
        timeframe=timeframe,
        year=year,
        rows=1,
        object_key=f"{timeframe}/{year}",
        sha256="a" * 64,
        first_timestamp=start.isoformat(),
        last_timestamp=(start + timedelta(hours=1)).isoformat(),
        reused_verified=reused,
    )


def test_dukascopy_writes_completed_year_before_later_year_fails(monkeypatch) -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    route = replace(route, minimum_history_days=0)
    written: list[int] = []

    monkeypatch.setattr(subject, "_load_valid_year_checkpoint", lambda *args, **kwargs: None)

    def fake_fetch(route, *, start, end, quality):
        if start.year == 2023:
            raise subject.ProviderError("reset on 2023-02-01")
        return [_candle(start), _candle(start + timedelta(hours=4))]

    monkeypatch.setattr(subject, "fetch_dukascopy_15m", fake_fetch)
    monkeypatch.setattr(
        subject,
        "_store_partition",
        lambda route, timeframe, year, rows, *, force: _fake_partition(
            timeframe, year, rows[0].timestamp, reused=False
        ),
    )

    def fake_checkpoint(route, *, year, start, end, quality, partitions):
        written.append(year)
        return f"checkpoint/{year}.json"

    monkeypatch.setattr(subject, "_write_year_checkpoint", fake_checkpoint)

    with pytest.raises(subject.ProviderError, match="reset on 2023"):
        subject._sync_dukascopy_incremental(
            route,
            start=datetime(2022, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 1, 1, tzinfo=timezone.utc),
            force=False,
        )

    assert written == [2022]


def test_dukascopy_resume_skips_verified_completed_year(monkeypatch) -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    route = replace(route, minimum_history_days=0)
    fetched: list[int] = []
    written: list[int] = []
    timeframes = ("15m", "1h", "4h", "1d")

    def fake_load(route, *, year, start, end, force):
        if year != 2022:
            return None
        return (
            [_fake_partition(item, year, start, reused=True) for item in timeframes],
            subject._empty_quality(),
        )

    def fake_fetch(route, *, start, end, quality):
        fetched.append(start.year)
        return [_candle(start), _candle(start + timedelta(hours=4))]

    monkeypatch.setattr(subject, "_load_valid_year_checkpoint", fake_load)
    monkeypatch.setattr(subject, "fetch_dukascopy_15m", fake_fetch)
    monkeypatch.setattr(
        subject,
        "_store_partition",
        lambda route, timeframe, year, rows, *, force: _fake_partition(
            timeframe, year, rows[0].timestamp, reused=False
        ),
    )

    def fake_checkpoint(route, *, year, start, end, quality, partitions):
        written.append(year)
        return f"checkpoint/{year}.json"

    monkeypatch.setattr(subject, "_write_year_checkpoint", fake_checkpoint)
    monkeypatch.setattr(subject.storage, "_put_json", lambda payload, key: None)

    result = subject._sync_dukascopy_incremental(
        route,
        start=datetime(2022, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, tzinfo=timezone.utc),
        force=False,
    )

    assert fetched == [2023]
    assert written == [2023]
    assert result["checkpoint_years_reused"] == 1
    assert result["checkpoint_years_written"] == 1
    assert result["status"] == "COMPLETE"


def test_year_checkpoint_requires_remote_partition_sha_match(monkeypatch) -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    end = datetime(2023, 1, 1, tzinfo=timezone.utc)
    partitions = [
        _fake_partition(item, 2022, start, reused=False) for item in ("15m", "1h", "4h", "1d")
    ]
    checkpoint = {
        "status": "COMPLETE_YEAR_CHECKPOINT",
        "route": subject._route_identity(route),
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "quality": subject._empty_quality(),
        "partitions": [subject.asdict(item) for item in partitions],
    }
    monkeypatch.setattr(subject, "_load_remote_json", lambda key: checkpoint)
    monkeypatch.setattr(subject.storage, "_remote_sha256", lambda key: "b" * 64)

    assert (
        subject._load_valid_year_checkpoint(route, year=2022, start=start, end=end, force=False)
        is None
    )


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
