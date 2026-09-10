from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.application.runtime_cycle import RuntimeCycleOrchestrator
from app.core.enums import PositionSide, PositionStatus
from app.core.models import Position
from app.journal.in_memory_repository import InMemoryJournalRepository
from app.journal.service import JournalService
from app.portfolio.account import Account
from app.runtime.audit import InMemoryCycleAuditRepository
from app.storage.repositories.in_memory_position_repository import InMemoryPositionRepository


def open_position() -> Position:
    return Position(
        position_id="P-1",
        symbol="BTC/USDT",
        side=PositionSide.LONG,
        entry_price=Decimal("100"),
        stop_loss=Decimal("95"),
        total_amount=Decimal("100"),
        quantity=Decimal("1"),
        leverage=Decimal("1"),
        take_profit=Decimal("110"),
    )


def historical_closed_position() -> Position:
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Position(
        position_id="OLD-1",
        symbol="ETH/USDT",
        side=PositionSide.SHORT,
        entry_price=Decimal("100"),
        stop_loss=Decimal("105"),
        total_amount=Decimal("200"),
        quantity=Decimal("2"),
        leverage=Decimal("1"),
        take_profit=Decimal("90"),
        status=PositionStatus.CLOSED,
        opened_at=opened,
        closed_at=opened + timedelta(hours=1),
        exit_price=Decimal("90"),
        realized_pnl=Decimal("20"),
        close_reason="TAKE_PROFIT",
    )


def test_runtime_journals_new_exit_once() -> None:
    positions = InMemoryPositionRepository([open_position()])
    journal = InMemoryJournalRepository()
    runner = RuntimeCycleOrchestrator(
        positions,
        lambda _: Decimal("94"),
        Account(Decimal("1000")),
        InMemoryCycleAuditRepository(),
        journal_service=JournalService(journal),
    )

    first = runner.run("C-JOURNAL")
    second = runner.run("C-JOURNAL")

    entry = journal.get("P-1")
    assert entry is not None
    assert entry.cycle_id == "C-JOURNAL"
    assert entry.realized_pnl == Decimal("-6")
    assert len(journal.list_all()) == 1
    assert any("Journaled position P-1" in note for note in first.notes)
    assert "idempotent replay" in second.notes[-1]


def test_runtime_repairs_missing_journal_for_historical_closed_position() -> None:
    positions = InMemoryPositionRepository([historical_closed_position()])
    journal = InMemoryJournalRepository()
    runner = RuntimeCycleOrchestrator(
        positions,
        lambda _: Decimal("100"),
        Account(Decimal("1000")),
        InMemoryCycleAuditRepository(),
        journal_service=JournalService(journal),
    )

    result = runner.run("C-RECOVER-JOURNAL")

    entry = journal.get("OLD-1")
    assert entry is not None
    assert entry.cycle_id is None
    assert entry.realized_pnl == Decimal("20")
    assert any("Journal reconciliation inspected=1 created=1" in note for note in result.notes)
