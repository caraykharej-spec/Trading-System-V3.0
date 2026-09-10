from __future__ import annotations

from abc import ABC, abstractmethod

from app.journal.models import JournalEntry


class JournalRepository(ABC):
    """Persistence contract for immutable completed-position journal entries."""

    @abstractmethod
    def save(self, entry: JournalEntry) -> bool:
        """Persist entry; return True when inserted and False for an identical replay."""
        raise NotImplementedError

    @abstractmethod
    def get(self, position_id: str) -> JournalEntry | None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self, symbol: str | None = None) -> list[JournalEntry]:
        raise NotImplementedError
