from __future__ import annotations

from app.core.models import Position
from app.storage.repositories.position_repository import PositionRepository


class InMemoryPositionRepository(PositionRepository):
    """Deterministic repository for unit tests and local PyCharm smoke runs."""

    def __init__(self, positions: list[Position] | None = None) -> None:
        self._positions: dict[str, Position] = {
            position.position_id: position for position in (positions or [])
        }

    def list_open(self) -> list[Position]:
        return [p for p in self._positions.values() if p.status.value == "OPEN"]

    def save(self, position: Position) -> None:
        self._positions[position.position_id] = position
