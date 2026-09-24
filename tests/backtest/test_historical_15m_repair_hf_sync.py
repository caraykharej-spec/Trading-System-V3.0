from __future__ import annotations

import json
import io
import lzma
import struct
import urllib.error
import zipfile
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


def _dukascopy_route():
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    return replace(
        route,
        provider="dukascopy",
        symbol="EURUSD",
        price_divisor=Decimal("100000"),
    )


def _histdata_zip(rows: str, *, symbol: str = "EURUSD", scope: str = "202411") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(f"DAT_ASCII_{symbol}_M1_{scope}.csv", rows)
        bundle.writestr(f"STATUS_{symbol}_{scope}.txt", "OK\n")
    return output.getvalue()


def test_registry_is_the_26_non_crypto_yahoo_intraday_repairs() -> None:
    routes = Historical15mRegistry.load().all()
    counts: dict[str, int] = {}
    for route in routes:
        counts[route.asset_class] = counts.get(route.asset_class, 0) + 1

    assert len(routes) == 26
    assert counts == {"commodity": 3, "equity": 16, "forex": 6, "index": 1}
    assert {route.provider for route in routes} == {"alpaca_sip", "histdata"}
    histdata = {route.base_asset: route.symbol for route in routes if route.provider == "histdata"}
    assert histdata == {
        "AUD": "AUDUSD",
        "EUR": "EURUSD",
        "GBP": "GBPUSD",
        "NZD": "NZDUSD",
        "SPX": "SPXUSD",
        "UKOIL": "BCOUSD",
        "USDCAD": "USDCAD",
        "USDCHF": "USDCHF",
        "XAG": "XAGUSD",
        "XAU": "XAUUSD",
    }
    assert Historical15mRegistry.load().get("NFLX").price_multiplier == Decimal("10")
    assert Historical15mRegistry.load().get("SPX").proxy_for == "SPX"


def test_parse_dukascopy_bi5_and_apply_reviewed_scale() -> None:
    route = _dukascopy_route()
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


def test_parse_histdata_ascii_converts_fixed_est_to_utc() -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    quality = subject._empty_quality()
    archive = _histdata_zip(
        "20241101 000000;1.10000;1.10020;1.09990;1.10010;0\n20241101 000100;broken\n"
    )

    rows = subject.parse_histdata_archive(archive, route, quality=quality)

    assert len(rows) == 1
    assert rows[0].timestamp == datetime(2024, 11, 1, 5, 0, tzinfo=timezone.utc)
    assert rows[0].open == Decimal("1.10000")
    assert rows[0].close == Decimal("1.10010")
    assert quality["invalid_rows_dropped"] == 1


def test_histdata_conflict_quarantines_entire_bucket_with_audit_evidence() -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    quality = subject._empty_quality()
    anomalies: list[dict[str, object]] = []
    archive = _histdata_zip(
        "20260705 173000;1.10;1.10;1.10;1.10;0\n"
        "20260705 173100;1.11;1.11;1.11;1.11;0\n"
        "20260705 173100;1.12;1.12;1.12;1.12;0\n"
        "20260705 174500;1.20;1.20;1.20;1.20;0\n"
    )

    rows = subject.parse_histdata_archive(archive, route, quality=quality, anomalies=anomalies)

    assert [row.timestamp for row in rows] == [datetime(2026, 7, 5, 22, 45, tzinfo=timezone.utc)]
    assert quality["conflicting_duplicate_timestamps"] == 1
    assert quality["quarantined_15m_buckets"] == 1
    assert quality["quarantined_source_rows"] == 2
    assert anomalies[0]["timestamp"] == "2026-07-05T22:31:00+00:00"
    assert anomalies[0]["bucket_15m_start"] == "2026-07-05T22:30:00+00:00"
    variants = anomalies[0]["variants"]
    assert isinstance(variants, list) and len(variants) == 2
    assert all(len(item["raw_sha256"]) == 64 for item in variants)


def test_histdata_identical_duplicate_is_deduplicated() -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    quality = subject._empty_quality()
    line = "20241101 000000;1.1;1.1;1.1;1.1;0\n"

    rows = subject.parse_histdata_archive(_histdata_zip(line + line), route, quality=quality)

    assert len(rows) == 1
    assert quality["identical_duplicate_rows_dropped"] == 1
    assert quality["quarantined_15m_buckets"] == 0


def test_histdata_past_year_archive_is_downloaded_once_for_utc_month(monkeypatch) -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    calls: list[tuple[int, int]] = []
    archive = _histdata_zip(
        "20241031 190000;1.1;1.1;1.1;1.1;0\n20241101 000000;1.2;1.2;1.2;1.2;0\n",
        scope="2024",
    )

    def fake_request(route, *, year, month):
        calls.append((year, month))
        return archive, "2024"

    monkeypatch.setattr(subject, "_request_histdata_archive", fake_request)
    rows, scopes = subject.fetch_histdata_15m(
        route,
        start=datetime(2024, 11, 1, tzinfo=timezone.utc),
        end=datetime(2024, 12, 1, tzinfo=timezone.utc),
        quality=subject._empty_quality(),
        archive_cache={},
    )

    assert calls == [(2024, 10)]
    assert scopes == ["2024"]
    assert [row.timestamp for row in rows] == [
        datetime(2024, 11, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2024, 11, 1, 5, 0, tzinfo=timezone.utc),
    ]


def test_histdata_archive_overlap_is_quarantined_and_counted(monkeypatch) -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    archives = {
        10: _histdata_zip("20261031 190000;1.1;1.1;1.1;1.1;0\n", scope="202610"),
        11: _histdata_zip(
            "20261031 190000;1.2;1.2;1.2;1.2;0\n20261101 000000;1.3;1.3;1.3;1.3;0\n",
            scope="202611",
        ),
    }

    monkeypatch.setattr(
        subject,
        "_request_histdata_archive",
        lambda route, *, year, month: (archives[month], f"2026-{month:02d}"),
    )
    anomalies: list[dict[str, object]] = []
    metrics: dict[str, object] = {}
    quality = subject._empty_quality()

    rows, _ = subject.fetch_histdata_15m(
        route,
        start=datetime(2026, 11, 1, tzinfo=timezone.utc),
        end=datetime(2026, 12, 1, tzinfo=timezone.utc),
        quality=quality,
        archive_cache={},
        anomalies=anomalies,
        metrics=metrics,
    )

    assert [row.timestamp for row in rows] == [datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc)]
    assert anomalies[0]["kind"] == "conflicting_archive_overlap_m1"
    assert {item["archive_scope"] for item in anomalies[0]["variants"]} == {
        "2026-10",
        "2026-11",
    }
    assert metrics["observed_15m_buckets_before_quarantine"] == 2
    assert metrics["conflicting_15m_buckets"] == 1
    assert metrics["conflict_ratio"] == 0.5


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
    route = _dukascopy_route()
    monkeypatch.setattr(
        subject,
        "_request_bytes",
        lambda url: (_ for _ in ()).throw(subject.ProviderError("historical data request failed")),
    )
    monkeypatch.setattr(subject, "_pace_dukascopy_request", lambda: None)
    monkeypatch.setenv("DUKASCOPY_DEFERRED_RETRY_SWEEPS", "1")

    with pytest.raises(subject.ProviderError, match=r"EUR/EURUSD failed on 2022-01-01"):
        subject.fetch_dukascopy_15m(
            route,
            start=datetime(2022, 1, 1, tzinfo=timezone.utc),
            end=datetime(2022, 1, 2, tzinfo=timezone.utc),
            quality=subject._empty_quality(),
        )


def test_dukascopy_defers_failed_day_and_recovers_after_other_days(monkeypatch) -> None:
    route = _dukascopy_route()
    calls: list[str] = []
    first_day_failed = False

    def fake_request(url: str) -> bytes:
        nonlocal first_day_failed
        day = url.split("/")[-2]
        calls.append(day)
        if day == "01" and not first_day_failed:
            first_day_failed = True
            raise subject.ProviderError("historical data HTTP 503")
        return day.encode()

    def fake_parse(payload, route, day, *, quality):
        return [_candle(datetime(day.year, day.month, day.day, tzinfo=timezone.utc))]

    monkeypatch.setattr(subject, "_request_bytes", fake_request)
    monkeypatch.setattr(subject, "parse_dukascopy_day", fake_parse)
    monkeypatch.setattr(subject, "_pace_dukascopy_request", lambda: None)
    monkeypatch.setattr(subject.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("DUKASCOPY_DEFERRED_RETRY_SWEEPS", "2")
    quality = subject._empty_quality()

    rows = subject.fetch_dukascopy_15m(
        route,
        start=datetime(2022, 1, 1, tzinfo=timezone.utc),
        end=datetime(2022, 1, 3, tzinfo=timezone.utc),
        quality=quality,
    )

    assert calls == ["01", "02", "01"]
    assert len(rows) == 2
    assert quality["pending_days_recovered"] == 1


def test_dukascopy_unresolved_days_are_reported_fail_closed(monkeypatch) -> None:
    route = _dukascopy_route()
    monkeypatch.setattr(
        subject,
        "_request_bytes",
        lambda url: (_ for _ in ()).throw(subject.ProviderError("historical data HTTP 503")),
    )
    monkeypatch.setattr(subject.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("DUKASCOPY_DEFERRED_RETRY_SWEEPS", "2")

    with pytest.raises(subject.DukascopyAcquisitionError) as error:
        subject.fetch_dukascopy_15m(
            route,
            start=datetime(2022, 1, 1, tzinfo=timezone.utc),
            end=datetime(2022, 1, 3, tzinfo=timezone.utc),
            quality=subject._empty_quality(),
        )

    assert error.value.evidence["pending_days"] == ["2022-01-01", "2022-01-02"]
    assert error.value.evidence["deferred_retry_sweeps"] == 2


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


def test_dukascopy_writes_completed_month_before_later_month_fails(monkeypatch) -> None:
    route = _dukascopy_route()
    route = replace(route, minimum_history_days=0)
    written: list[str] = []

    monkeypatch.setattr(subject, "_load_valid_year_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(subject, "_load_valid_month_checkpoint", lambda *args, **kwargs: None)

    def fake_fetch(route, *, start, end, quality):
        if start.month == 2:
            raise subject.DukascopyAcquisitionError(
                "reset on 2022-02-01",
                evidence={"failed_date": "2022-02-01", "pending_days": ["2022-02-01"]},
            )
        return [_candle(start), _candle(start + timedelta(hours=4))]

    monkeypatch.setattr(subject, "fetch_dukascopy_15m", fake_fetch)
    monkeypatch.setattr(
        subject,
        "_store_partition",
        lambda route, timeframe, year, rows, *, force, month=None: replace(
            _fake_partition(timeframe, year, rows[0].timestamp, reused=False),
            rows=len(rows),
            last_timestamp=rows[-1].timestamp.isoformat(),
            month=month,
        ),
    )

    def fake_checkpoint(route, *, year, month, start, end, quality, partitions):
        written.append(f"{year:04d}-{month:02d}")
        return f"checkpoint/{year}/{month}.json"

    monkeypatch.setattr(subject, "_write_month_checkpoint", fake_checkpoint)

    with pytest.raises(subject.DukascopyAcquisitionError, match="reset on 2022-02") as error:
        subject._sync_dukascopy_incremental(
            route,
            start=datetime(2022, 1, 1, tzinfo=timezone.utc),
            end=datetime(2022, 3, 1, tzinfo=timezone.utc),
            force=False,
            validation_scope="full",
        )

    assert written == ["2022-01"]
    assert error.value.evidence["months_written"] == ["2022-01"]
    assert error.value.evidence["failed_month"] == "2022-02"


def test_dukascopy_resume_prefers_legacy_year_then_month_checkpoint(monkeypatch) -> None:
    route = _dukascopy_route()
    route = replace(route, minimum_history_days=0)
    fetched: list[str] = []
    written: list[str] = []
    timeframes = ("15m", "1h", "4h", "1d")

    def fake_load(route, *, year, start, end, force):
        if year != 2022:
            return None
        return (
            [_fake_partition(item, year, start, reused=True) for item in timeframes],
            subject._empty_quality(),
        )

    def fake_month_load(route, *, year, month, start, end, force):
        if year == 2023 and month == 1:
            return (
                [
                    replace(_fake_partition(item, year, start, reused=True), month=month)
                    for item in timeframes
                ],
                subject._empty_quality(),
                [],
                {},
            )
        return None

    def fake_fetch(route, *, start, end, quality):
        fetched.append(f"{start.year:04d}-{start.month:02d}")
        return [_candle(start), _candle(end - timedelta(days=1))]

    monkeypatch.setattr(subject, "_load_valid_year_checkpoint", fake_load)
    monkeypatch.setattr(subject, "_load_valid_month_checkpoint", fake_month_load)
    monkeypatch.setattr(subject, "fetch_dukascopy_15m", fake_fetch)
    monkeypatch.setattr(
        subject,
        "_store_partition",
        lambda route, timeframe, year, rows, *, force, month=None: replace(
            _fake_partition(timeframe, year, rows[0].timestamp, reused=False),
            rows=len(rows),
            last_timestamp=rows[-1].timestamp.isoformat(),
            month=month,
        ),
    )

    def fake_checkpoint(
        route, *, year, month, start, end, quality, partitions, source_anomalies=None
    ):
        written.append(f"{year:04d}-{month:02d}")
        return f"checkpoint/{year}/{month}.json"

    monkeypatch.setattr(subject, "_write_month_checkpoint", fake_checkpoint)
    monkeypatch.setattr(subject.storage, "_put_json", lambda payload, key: None)

    result = subject._sync_dukascopy_incremental(
        route,
        start=datetime(2022, 1, 1, tzinfo=timezone.utc),
        end=datetime(2023, 3, 1, tzinfo=timezone.utc),
        force=False,
        validation_scope="full",
    )

    assert fetched == ["2023-02"]
    assert written == ["2023-02"]
    assert result["checkpoint_years_reused"] == 1
    assert result["checkpoint_months_reused"] == 1
    assert result["checkpoint_months_written"] == 1
    assert result["status"] == "COMPLETE"


def test_histdata_sync_writes_monthly_checkpoint_with_progress(monkeypatch, capsys) -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    start = datetime(2024, 11, 1, tzinfo=timezone.utc)
    written: list[str] = []

    monkeypatch.setattr(subject, "_load_valid_month_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        subject,
        "fetch_histdata_15m",
        lambda route, *, start, end, quality, archive_cache, anomalies=None, metrics=None: (
            metrics.update(
                {
                    "observed_15m_buckets_before_quarantine": 2,
                    "conflicting_15m_buckets": 0,
                    "conflict_ratio": 0.0,
                    "archive_scopes": ["2024"],
                }
            )
            or [_candle(start), _candle(end - timedelta(days=1))],
            ["2024"],
        ),
    )
    monkeypatch.setattr(
        subject,
        "_store_partition",
        lambda route, timeframe, year, rows, *, force, month=None: replace(
            _fake_partition(timeframe, year, rows[0].timestamp, reused=False),
            rows=len(rows),
            last_timestamp=rows[-1].timestamp.isoformat(),
            month=month,
        ),
    )

    def fake_checkpoint(
        route,
        *,
        year,
        month,
        start,
        end,
        quality,
        partitions,
        source_anomalies=None,
        source_quality_metrics=None,
    ):
        written.append(f"{year:04d}-{month:02d}")
        return f"checkpoint/{year}/{month}.json"

    monkeypatch.setattr(subject, "_write_month_checkpoint", fake_checkpoint)
    monkeypatch.setattr(subject.storage, "_put_json", lambda payload, key: None)

    result = subject.sync_route(
        route,
        start=start,
        end=datetime(2024, 12, 1, tzinfo=timezone.utc),
        validation_scope="targeted",
    )

    assert written == ["2024-11"]
    assert result["route"]["provider"] == "histdata"
    assert result["months_written"] == ["2024-11"]
    assert result["validation_scope"] == "targeted"
    assert result["minimum_history_days_enforced"] is False
    assert result["archive_scopes_downloaded"] == ["2024"]
    assert '"event": "histdata_month_complete"' in capsys.readouterr().out


def test_histdata_sync_fails_closed_above_monthly_conflict_limit(monkeypatch) -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    start = datetime(2024, 11, 1, tzinfo=timezone.utc)
    monkeypatch.setenv("HISTDATA_MAX_CONFLICT_BUCKETS_ABSOLUTE_PER_MONTH", "1")
    monkeypatch.setenv("HISTDATA_MAX_CONFLICT_BUCKET_RATIO", "1")
    monkeypatch.setattr(subject, "_load_valid_month_checkpoint", lambda *args, **kwargs: None)

    def fake_fetch(route, *, start, end, quality, archive_cache, anomalies, metrics):
        anomalies.extend(
            [
                {"bucket_15m_start": "2024-11-03T10:00:00+00:00"},
                {"bucket_15m_start": "2024-11-04T10:00:00+00:00"},
            ]
        )
        metrics.update(
            {
                "observed_15m_buckets_before_quarantine": 100,
                "conflicting_15m_buckets": 2,
                "conflict_ratio": 0.02,
                "archive_scopes": ["2024"],
            }
        )
        return [_candle(start), _candle(end - timedelta(days=1))], ["2024"]

    monkeypatch.setattr(subject, "fetch_histdata_15m", fake_fetch)

    with pytest.raises(subject.HistDataAcquisitionError, match="limits are 1") as error:
        subject._sync_histdata_incremental(
            route,
            start=start,
            end=datetime(2024, 12, 1, tzinfo=timezone.utc),
            force=False,
            validation_scope="targeted",
        )

    assert error.value.evidence["failed_month"] == "2024-11"
    assert len(error.value.evidence["source_anomalies"]) == 2


def test_histdata_sync_fails_closed_above_ratio_limit(monkeypatch) -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    start = datetime(2024, 11, 1, tzinfo=timezone.utc)
    monkeypatch.setenv("HISTDATA_MAX_CONFLICT_BUCKETS_ABSOLUTE_PER_MONTH", "20")
    monkeypatch.setenv("HISTDATA_MAX_CONFLICT_BUCKET_RATIO", "0.01")
    monkeypatch.setattr(subject, "_load_valid_month_checkpoint", lambda *args, **kwargs: None)

    def fake_fetch(route, *, start, end, quality, archive_cache, anomalies, metrics):
        anomalies.append({"bucket_15m_start": "2024-11-03T10:00:00+00:00"})
        metrics.update(
            {
                "observed_15m_buckets_before_quarantine": 50,
                "conflicting_15m_buckets": 1,
                "conflict_ratio": 0.02,
                "archive_scopes": ["2024"],
            }
        )
        return [_candle(start), _candle(end - timedelta(days=1))], ["2024"]

    monkeypatch.setattr(subject, "fetch_histdata_15m", fake_fetch)

    with pytest.raises(subject.HistDataAcquisitionError) as error:
        subject._sync_histdata_incremental(
            route,
            start=start,
            end=datetime(2024, 12, 1, tzinfo=timezone.utc),
            force=False,
            validation_scope="targeted",
        )

    metrics = error.value.evidence["source_quality_metrics"]
    assert metrics["policy_decision"] == "FAIL"
    assert metrics["policy_reasons"] == ["ratio_limit_exceeded"]


def test_targeted_validation_accepts_requested_month_without_three_year_history() -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    start = datetime(2024, 11, 1, tzinfo=timezone.utc)
    end = datetime(2024, 12, 1, tzinfo=timezone.utc)
    partition = replace(
        _fake_partition("15m", 2024, start, reused=True),
        rows=2004,
        last_timestamp=(end - timedelta(days=2)).isoformat(),
        month=11,
    )

    subject._validate_partition_coverage(
        route,
        [partition],
        start=start,
        end=end,
        validation_scope="targeted",
    )


def test_full_validation_still_requires_minimum_history() -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    start = datetime(2024, 11, 1, tzinfo=timezone.utc)
    end = datetime(2024, 12, 1, tzinfo=timezone.utc)
    partition = replace(
        _fake_partition("15m", 2024, start, reused=True),
        rows=2004,
        last_timestamp=(end - timedelta(days=2)).isoformat(),
        month=11,
    )

    with pytest.raises(subject.ProviderError, match="required 1095"):
        subject._validate_partition_coverage(
            route,
            [partition],
            start=start,
            end=end,
            validation_scope="full",
        )


def test_targeted_validation_rejects_materially_incomplete_requested_end() -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    start = datetime(2024, 11, 1, tzinfo=timezone.utc)
    end = datetime(2024, 12, 1, tzinfo=timezone.utc)
    partition = _fake_partition("15m", 2024, start, reused=True)

    with pytest.raises(subject.ProviderError, match="ends materially before"):
        subject._validate_partition_coverage(
            route,
            [partition],
            start=start,
            end=end,
            validation_scope="targeted",
        )


def test_year_checkpoint_requires_remote_partition_sha_match(monkeypatch) -> None:
    route = _dukascopy_route()
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


def test_month_checkpoint_reuses_only_sha_verified_partitions(monkeypatch) -> None:
    route = Historical15mRegistry.load().get("EUR")
    assert route is not None
    start = datetime(2024, 11, 1, tzinfo=timezone.utc)
    end = datetime(2024, 12, 1, tzinfo=timezone.utc)
    partitions = [
        replace(_fake_partition(item, 2024, start, reused=False), month=11)
        for item in ("15m", "1h", "4h", "1d")
    ]
    checkpoint = {
        "status": "COMPLETE_MONTH_CHECKPOINT",
        "route": subject._route_identity(route),
        "year": 2024,
        "month": 11,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "quality": subject._empty_quality(),
        "partitions": [subject.asdict(item) for item in partitions],
    }
    monkeypatch.setattr(subject, "_load_remote_json", lambda key: checkpoint)
    monkeypatch.setattr(subject.storage, "_remote_sha256", lambda key: "a" * 64)

    loaded = subject._load_valid_month_checkpoint(
        route, year=2024, month=11, start=start, end=end, force=False
    )

    assert loaded is not None
    assert {item.month for item in loaded[0]} == {11}
    assert all(item.reused_verified for item in loaded[0])
    assert loaded[2] == []
    assert loaded[3]["observed_15m_buckets_before_quarantine"] == 1


def test_error_artifact_includes_resume_evidence(tmp_path, monkeypatch) -> None:
    output = tmp_path / "route-summary.json"
    monkeypatch.setattr(
        subject.argparse.ArgumentParser,
        "parse_args",
        lambda self: subject.argparse.Namespace(
            discover_only=False,
            base_asset="EUR",
            start="2022-01-01T00:00:00+00:00",
            end="2022-02-01T00:00:00+00:00",
            force=False,
            validation_scope="targeted",
            output=str(output),
        ),
    )
    monkeypatch.setattr(
        subject,
        "sync_route",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subject.DukascopyAcquisitionError(
                "failed",
                evidence={
                    "failed_month": "2022-01",
                    "months_written": [],
                    "pending_days": ["2022-01-15"],
                },
            )
        ),
    )

    with pytest.raises(subject.DukascopyAcquisitionError):
        subject.main()

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "ERROR"
    assert payload["resume_evidence"]["failed_month"] == "2022-01"
    assert payload["resume_evidence"]["pending_days"] == ["2022-01-15"]


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
            validation_scope="full",
            output=str(output),
        ),
    )

    assert subject.main() == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["route_count"] == 26
