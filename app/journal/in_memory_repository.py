from __future__ import annotations

from app.journal.models import JournalEntry
from app.journal.repository import JournalRepository


class InMemoryJournalRepository(JournalRepository):
    def __init__(self, entries: list[JournalEntry] | None = None) -> None:
        self._entries: dict[str, JournalEntry] = {}
        for entry in entries or []:
            self.save(entry)

    def save(self, entry: JournalEntry) -> bool:
        existing = self._entries.get(entry.position_id)
        if existing is not None:
            if existing == entry:
                return False
            raise ValueError(f"journal conflict for position {entry.position_id}")
        self._entries[entry.position_id] = entry
        return True

    def get(self, position_id: str) -> JournalEntry | None:
        return self._entries.get(position_id)

    def list_all(self, symbol: str | None = None) -> list[JournalEntry]:
        entries = list(self._entries.values())
        if symbol is not None:
            entries = [entry for entry in entries if entry.symbol == symbol]
        return sorted(entries, key=lambda entry: (entry.closed_at, entry.position_id))
