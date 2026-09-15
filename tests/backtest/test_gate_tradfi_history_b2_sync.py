from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from scripts.backtest.sync_gate_tradfi_history_to_b2 import (
    _extract_rows,
    _month_groups,
    _page_url,
    _parse_kline_rows,
    fetch_all_history,
)
from scripts.backtest.sync_gate_universe_history_to_b2 import GateHistoryRoute


def _route(multiplier: str = "1") -> GateHistoryRoute:
    return GateHistoryRoute(
        canonical_symbol="TEST/USD",
        base_asset="TEST",
        asset_class="equity",
        provider="gateio_tradfi",
        provider_symbol="TEST",
        price_multiplier=multiplier,
        route_origin="test",
    )


def test_extract_rows_accepts_common_gate_envelopes() -> None:
    row = {"t": 900, "o": "1", "c": "2", "h": "3", "l": "0.5"}
    assert _extract_rows([row]) == [row]
    assert _extract_rows({"data": [row]}) == [row]
    assert _extract_rows({"data": {"list": [row]}}) == [row]


def test_parse_kline_rows_applies_multiplier_sorts_and_dedupes() -> None:
    payload = [
        {"t": 1800, "o": "2", "c": "2.5", "h": "3", "l": "1.5"},
        {"t": 900, "o": "1", "c": "1.5", "h": "2", "l": "0.5"},
        {"t": 900, "o": "1", "c": "1.5", "h": "2", "l": "0.5"},
    ]
    rows = _parse_kline_rows(payload, _route("10"), "15m")
    assert [int(item.timestamp.timestamp()) for item in rows] == [900, 1800]
    assert rows[0].open == Decimal("10")
    assert rows[0].close == Decimal("15")
    assert rows[0].high == Decimal("20")
    assert rows[0].low == Decimal("5.0")


def test_parse_kline_rows_rejects_bad_alignment() -> None:
    with pytest.raises(Exception, match="not aligned"):
        _parse_kline_rows(
            [{"t": 901, "o": "1", "c": "1", "h": "1", "l": "1"}],
            _route(),
            "15m",
        )


def test_parse_kline_rows_rejects_ohlc_violation() -> None:
    with pytest.raises(Exception, match="OHLC invariant"):
        _parse_kline_rows(
            [{"t": 900, "o": "5", "c": "1", "h": "4", "l": "0"}],
            _route(),
            "15m",
        )


def test_month_groups_are_chronological() -> None:
    rows = _parse_kline_rows(
        [
            {"t": int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp()), "o": "1", "c": "1", "h": "1", "l": "1"},
            {"t": int(datetime(2026, 1, 31, 23, 45, tzinfo=timezone.utc).timestamp()), "o": "1", "c": "1", "h": "1", "l": "1"},
        ],
        _route(),
        "15m",
    )
    groups = list(_month_groups(rows))
    assert [item[0] for item in groups] == [(2026, 1), (2026, 2)]


def test_page_url_encodes_required_gate_contract() -> None:
    url = _page_url("XAUUSD", "1h", 123456)
    assert "/tradfi/symbols/XAUUSD/klines?" in url
    assert "kline_type=1h" in url
    assert "end_time=123456" in url
    assert "limit=500" in url


def test_fetch_all_history_paginates_backward_until_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    pages = [
        [
            {"t": 3600, "o": "1", "c": "1", "h": "1", "l": "1"},
            {"t": 7200, "o": "1", "c": "1", "h": "1", "l": "1"},
        ],
        [
            {"t": 0, "o": "1", "c": "1", "h": "1", "l": "1"},
        ],
        [],
    ]

    def fake_request(url: str) -> object:
        calls.append(url)
        return pages[len(calls) - 1]

    monkeypatch.setattr(
        "scripts.backtest.sync_gate_tradfi_history_to_b2._request_json", fake_request
    )
    monkeypatch.setenv("GATE_TRADFI_REQUEST_DELAY", "0")
    rows, page_count = fetch_all_history(
        _route(),
        "1h",
        end=datetime.fromtimestamp(10800, tz=timezone.utc),
        max_pages=10,
    )
    assert page_count == 3
    assert [int(item.timestamp.timestamp()) for item in rows] == [0, 3600, 7200]
    assert "end_time=10799" in calls[0]
    assert "end_time=3599" in calls[1]
    assert "end_time=-1" in calls[2]
