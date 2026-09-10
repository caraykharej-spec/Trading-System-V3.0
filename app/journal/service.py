from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.core.models import Position
from app.journal.models import JournalEntry
from app.journal.repository import JournalRepository


@dataclass(frozen=True)
class JournalReconciliationResult:
    inspected: int
    created: int
    existing: int


class JournalService:
    """Creates immutable trade-journal facts and repairs missing journal rows."""

    def __init__(self, repository: JournalRepository) -> None:
        self.repository = repository

    def record_closed_position(
        self, position: Position, cycle_id: str | None = None
    ) -> JournalEntry:
        entry = JournalEntry.from_position(position, cycle_id=cycle_id)
        self.repository.save(entry)
        return entry

    def reconcile(self, positions: Iterable[Position]) -> JournalReconciliationResult:
        inspected = created = existing = 0
        for position in positions:
            inspected += 1
            current = self.repository.get(position.position_id)
            if current is not None:
                expected = JournalEntry.from_position(position, cycle_id=current.cycle_id)
                if current != expected:
                    raise ValueError(f"journal conflict for position {position.position_id}")
                existing += 1
                continue
            entry = JournalEntry.from_position(position, cycle_id=None)
            if self.repository.save(entry):
                created += 1
            else:
                existing += 1
        return JournalReconciliationResult(inspected, created, existing)
