from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.models import Position


class PositionRepository(ABC):
    """Persistence contract used by the application layer."""

    @abstractmethod
    def list_open(self) -> list[Position]:
        raise NotImplementedError

    @abstractmethod
    def list_closed(self) -> list[Position]:
        raise NotImplementedError

    @abstractmethod
    def save(self, position: Position) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(self, position_id: str) -> bool:
        raise NotImplementedError
