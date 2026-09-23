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
    return urllib.error.HTTPError(
        "https://example.test/file.bi5", status, "failure", headers, None
    )


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
