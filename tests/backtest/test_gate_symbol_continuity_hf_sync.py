from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.data.market_data import Candle
from scripts.backtest import sync_gate_symbol_continuity_to_hf as subject
from scripts.backtest import sync_gate_universe_history_to_b2 as core


def _candle(symbol: str, timestamp: datetime, close: str) -> Candle:
    value = Decimal(close)
    return Candle(
        symbol=symbol,
        timeframe="5m",
        timestamp=timestamp,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("1"),
    )


def test_continuity_stitches_adjacent_source_symbols_without_overlap(monkeypatch) -> None:
    boundary = datetime(2026, 6, 16, 14, tzinfo=timezone.utc)
    before = boundary.replace(hour=13, minute=55)
    after = boundary
    calls: list[tuple[str, datetime, datetime]] = []

    def fake_fetch(route, start, end):
        calls.append((route.provider_symbol, start, end))
        if route.provider_symbol == "TON_USDT":
            return ([_candle(route.canonical_symbol, before, "1")], 1, 0, 0, 1, 0)
        if route.provider_symbol == "GRAM_USDT":
            return ([_candle(route.canonical_symbol, after, "2")], 1, 0, 0, 1, 0)
        raise AssertionError(route.provider_symbol)

    monkeypatch.setattr(subject, "_NATIVE_FETCH_MONTH_5M", fake_fetch)
    route = core.GateHistoryRoute(
        canonical_symbol="TON/USDT",
        base_asset="TON",
        asset_class="crypto",
        provider="gateio",
        provider_symbol="GRAM_USDT",
        route_origin="source_registry_historical_symbol_continuity",
    )
    segments = (
        subject.ContinuitySegment(
            "TON_USDT",
            datetime(2023, 1, 1, tzinfo=timezone.utc),
            boundary,
        ),
        subject.ContinuitySegment("GRAM_USDT", boundary, None),
    )

    rows, found, missing, rest, monthly, daily = subject.fetch_continuity_month_5m(
        route,
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        segments,
    )

    assert [row.timestamp for row in rows] == [before, after]
    assert all(row.symbol == "TON/USDT" for row in rows)
    assert calls == [
        ("TON_USDT", datetime(2026, 6, 1, tzinfo=timezone.utc), boundary),
        ("GRAM_USDT", boundary, datetime(2026, 7, 1, tzinfo=timezone.utc)),
    ]
    assert (found, missing, rest, monthly, daily) == (2, 0, 0, 2, 0)


def test_continuity_fails_on_conflicting_boundary_candle(monkeypatch) -> None:
    boundary = datetime(2026, 6, 16, 14, tzinfo=timezone.utc)
    route = core.GateHistoryRoute(
        canonical_symbol="TON/USDT",
        base_asset="TON",
        asset_class="crypto",
        provider="gateio",
        provider_symbol="GRAM_USDT",
    )
    overlapping = (
        subject.ContinuitySegment("TON_USDT", boundary, None),
        subject.ContinuitySegment("GRAM_USDT", boundary, None),
    )

    def fake_fetch(source_route, start, end):
        close = "1" if source_route.provider_symbol == "TON_USDT" else "2"
        return ([_candle(source_route.canonical_symbol, boundary, close)], 1, 0, 0, 1, 0)

    monkeypatch.setattr(subject, "_NATIVE_FETCH_MONTH_5M", fake_fetch)

    try:
        subject.fetch_continuity_month_5m(
            route,
            boundary,
            boundary.replace(day=17),
            overlapping,
        )
    except Exception as exc:
        assert "conflicting candles" in str(exc)
    else:
        raise AssertionError("expected continuity conflict")


def test_project_ton_rule_has_exact_rename_boundary() -> None:
    rule = subject.load_rule("TON")

    assert rule.target_provider_symbol == "GRAM_USDT"
    assert [segment.source_provider_symbol for segment in rule.segments] == [
        "TON_USDT",
        "GRAM_USDT",
    ]
    assert rule.segments[0].end == rule.segments[1].start
    assert rule.segments[0].end == datetime(2026, 6, 16, 14, tzinfo=timezone.utc)
