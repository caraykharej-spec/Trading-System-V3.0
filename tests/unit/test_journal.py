from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3

import pytest

from app.core.enums import PositionSide, PositionStatus
from app.core.models import Position
from app.journal.in_memory_repository import InMemoryJournalRepository
from app.journal.models import JournalEntry
from app.journal.service import JournalService
from app.journal.sqlite_repository import SQLiteJournalRepository
from app.storage.database import SCHEMA


def closed_position(position_id: str = "P-1", symbol: str = "BTC/USDT") -> Position:
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Position(
        position_id=position_id,
        symbol=symbol,
        side=PositionSide.LONG,
        entry_price=Decimal("100"),
        stop_loss=Decimal("95"),
        total_amount=Decimal("100"),
        quantity=Decimal("1"),
        leverage=Decimal("1"),
        take_profit=Decimal("110"),
        status=PositionStatus.STOPPED_OUT,
        opened_at=opened,
        closed_at=opened + timedelta(hours=2),
        exit_price=Decimal("94"),
        realized_pnl=Decimal("-6"),
        close_reason="STOP_LOSS",
    )


def test_journal_entry_is_built_from_closed_position() -> None:
    entry = JournalEntry.from_position(closed_position(), cycle_id="C-1")
    assert entry.position_id == "P-1"
    assert entry.cycle_id == "C-1"
    assert entry.realized_pnl == Decimal("-6")
    assert entry.return_percent == Decimal("-6")


def test_open_position_cannot_be_journaled() -> None:
    position = closed_position()
    position.status = PositionStatus.OPEN
    with pytest.raises(ValueError, match="open position"):
        JournalEntry.from_position(position)


def test_in_memory_journal_is_idempotent_and_detects_conflict() -> None:
    repository = InMemoryJournalRepository()
    entry = JournalEntry.from_position(closed_position(), cycle_id="C-1")
    assert repository.save(entry) is True
    assert repository.save(entry) is False
    with pytest.raises(ValueError, match="journal conflict"):
        repository.save(replace(entry, realized_pnl=Decimal("-7")))


def test_sqlite_journal_round_trip_and_symbol_filter() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(SCHEMA)
    repository = SQLiteJournalRepository(connection)
    entry = JournalEntry.from_position(closed_position(), cycle_id="C-1")

    assert repository.save(entry) is True
    assert repository.save(entry) is False
    assert repository.get("P-1") == entry
    assert repository.list_all("BTC/USDT") == [entry]
    assert repository.list_all("ETH/USDT") == []


def test_journal_reconciliation_repairs_missing_rows_idempotently() -> None:
    repository = InMemoryJournalRepository()
    service = JournalService(repository)
    positions = [closed_position("P-1"), closed_position("P-2", "ETH/USDT")]

    first = service.reconcile(positions)
    second = service.reconcile(positions)

    assert (first.inspected, first.created, first.existing) == (2, 2, 0)
    assert (second.inspected, second.created, second.existing) == (2, 0, 2)
    assert len(repository.list_all()) == 2
