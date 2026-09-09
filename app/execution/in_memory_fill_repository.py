from __future__ import annotations

from .fill_repository import FillRepository
from .fills import Fill


class InMemoryFillRepository(FillRepository):
    """Append-only fill ledger for tests and local runtime."""

    def __init__(self) -> None:
        self._fills: dict[str, Fill] = {}

    def save(self, fill: Fill) -> None:
        existing = self._fills.get(fill.fill_id)
        if existing is not None and existing != fill:
            raise ValueError(f"Conflicting fill: {fill.fill_id}")
        self._fills[fill.fill_id] = fill

    def get(self, fill_id: str) -> Fill | None:
        return self._fills.get(fill_id)

    def list_for_order(self, order_id: str) -> list[Fill]:
        return [fill for fill in self._fills.values() if fill.order_id == order_id]
