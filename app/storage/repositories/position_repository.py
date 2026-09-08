from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.models import Position


class PositionRepository(ABC):
    """Persistence contract used by the application layer."""

    @abstractmethod
    def list_open(self) -> list[Position]:
        raise NotImplementedError

    @abstractmethod
    def save(self, position: Position) -> None:
        raise NotImplementedError
