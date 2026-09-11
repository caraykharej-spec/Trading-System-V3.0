from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.assistant import (
    AssistantAnalyticsService,
    AssistantIntent,
    AssistantIntentRouter,
    AssistantOrchestrator,
)
from app.copilot.models import CopilotItemBrief, CopilotMarketBrief, CopilotStatus
from app.core.enums import PositionSide
from app.core.models import Position
from app.data.market_data import Candle
from app.journal.models import JournalEntry


UTC = timezone.utc
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _brief() -> CopilotMarketBrief:
    return CopilotMarketBrief(
        evaluated=1,
        strategy_qualified=1,
        context_rejected=0,
        risk_rejected=0,
        portfolio_rejected=0,
        items=(
            CopilotItemBrief(
                symbol="BTCUSD",
                status=CopilotStatus.QUALIFIED,
                title="BTCUSD",
                narrative=("qualified",),
            ),
        ),
    )


def _position() -> Position:
    return Position(
        position_id="pos-1",
        symbol="BTCUSD",
        side=PositionSide.LONG,
        entry_price=Decimal("100"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("130"),
        total_amount=Decimal("1000"),
        quantity=Decimal("10"),
        leverage=Decimal("2"),
        opened_at=NOW - timedelta(hours=2),
    )


def _journal_entry() -> JournalEntry:
    return JournalEntry(
        position_id="closed-1",
        symbol="BTCUSD",
        side=PositionSide.LONG,
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        total_amount=Decimal("1000"),
        quantity=Decimal("10"),
        leverage=Decimal("1"),
        realized_pnl=Decimal("100"),
        opened_at=NOW - timedelta(days=1),
        closed_at=NOW - timedelta(hours=1),
        close_reason="TAKE_PROFIT",
    )


def _candles(symbol: str, timeframe: str, limit: int) -> list[Candle]:
    assert symbol == "BTCUSD"
    assert limit == 2
    return [
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=NOW - timedelta(hours=2),
            open=Decimal("99"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("100"),
            volume=Decimal("10"),
        ),
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=NOW - timedelta(hours=1),
            open=Decimal("100"),
            high=Decimal("106"),
            low=Decimal("99"),
            close=Decimal("105"),
            volume=Decimal("12"),
        ),
    ]


def _analytics(position: Position | None = None) -> AssistantAnalyticsService:
    positions = [] if position is None else [position]
    return AssistantAnalyticsService(
        positions_provider=lambda: positions,
        journal_provider=lambda: [_journal_entry()],
        live_price_provider=lambda symbol: Decimal("110"),
        candles_provider=_candles,
    )


def test_positions_are_grounded_with_read_only_unrealized_pnl() -> None:
    assistant = AssistantOrchestrator(
        _brief,
        analytics=_analytics(_position()),
        symbols_provider=lambda: ("BTCUSD",),
    )

    response = assistant.ask("show BTCUSD positions")

    assert response.intent is AssistantIntent.POSITIONS
    assert response.symbol == "BTCUSD"
    assert response.execution_authority is False
    values = {item.key: item.value for item in response.citations}
    assert values["pos-1_current_price"] == "110"
    assert values["pos-1_unrealized_pnl"] == "200.0"


def test_journal_summary_uses_authoritative_completed_trade_history() -> None:
    assistant = AssistantOrchestrator(
        _brief,
        analytics=_analytics(),
        symbols_provider=lambda: ("BTCUSD",),
    )

    response = assistant.ask("BTCUSD journal")

    assert response.intent is AssistantIntent.JOURNAL
    values = {item.key: item.value for item in response.citations}
    assert values["total_trades"] == "1"
    assert values["net_pnl"] == "100"
    assert values["win_rate_percent"] == "100"
    assert any(item.source == "journal" for item in response.citations)


def test_market_change_compares_live_price_to_prior_completed_candle() -> None:
    assistant = AssistantOrchestrator(
        _brief,
        analytics=_analytics(),
        symbols_provider=lambda: ("BTCUSD",),
    )

    response = assistant.ask("what changed in BTCUSD market?")

    assert response.intent is AssistantIntent.MARKET_CHANGE
    values = {item.key: item.value for item in response.citations}
    assert values["current_price"] == "110"
    assert values["15m_reference_close"] == "100"
    assert values["15m_change_percent"] == "10.0"
    assert values["1d_change_percent"] == "10.0"


def test_what_if_is_hypothetical_and_does_not_mutate_position() -> None:
    position = _position()
    original = (position.stop_loss, position.take_profit, position.leverage)
    assistant = AssistantOrchestrator(
        _brief,
        analytics=_analytics(position),
        symbols_provider=lambda: ("BTCUSD",),
    )

    response = assistant.ask("what if BTCUSD rises 10%?")

    assert response.intent is AssistantIntent.WHAT_IF
    assert response.execution_authority is False
    values = {item.key: item.value for item in response.citations}
    assert values["scenario_percent"] == "10"
    assert values["hypothetical_price"] == "121.0"
    assert values["pos-1_hypothetical_pnl"] == "420.00"
    assert values["pos-1_pnl_delta"] == "220.00"
    assert (position.stop_loss, position.take_profit, position.leverage) == original


def test_what_if_router_infers_negative_direction_and_requires_bounded_percent() -> None:
    router = AssistantIntentRouter()

    route = router.route("what if BTCUSD falls 5%?", ("BTCUSD",))

    assert route.intent is AssistantIntent.WHAT_IF
    assert route.scenario_percent == Decimal("-5")

    try:
        router.route("what if BTCUSD falls 100%?", ("BTCUSD",))
    except ValueError as exc:
        assert "greater than -100" in str(exc)
    else:
        raise AssertionError("non-positive hypothetical price must be rejected")


def test_analytics_intents_do_not_force_copilot_scan_when_symbols_are_supplied() -> None:
    calls = 0

    def failing_brief() -> CopilotMarketBrief:
        nonlocal calls
        calls += 1
        raise AssertionError("copilot brief must not load for analytics intent")

    assistant = AssistantOrchestrator(
        failing_brief,
        analytics=_analytics(),
        symbols_provider=lambda: ("BTCUSD",),
    )

    response = assistant.ask("BTCUSD journal")

    assert response.intent is AssistantIntent.JOURNAL
    assert calls == 0


def test_what_if_without_explicit_percent_fails_closed() -> None:
    assistant = AssistantOrchestrator(
        _brief,
        analytics=_analytics(),
        symbols_provider=lambda: ("BTCUSD",),
    )

    response = assistant.ask("what if BTCUSD changes?")

    assert response.intent is AssistantIntent.WHAT_IF
    assert response.citations == ()
    assert "scenario_percent" in response.unknowns
    assert response.text.startswith("UNKNOWN")
