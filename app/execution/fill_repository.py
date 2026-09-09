from __future__ import annotations

from abc import ABC, abstractmethod

from .fills import Fill


class FillRepository(ABC):
    """Append-only persistence contract for execution fills."""

    @abstractmethod
    def save(self, fill: Fill) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, fill_id: str) -> Fill | None:
        raise NotImplementedError

    @abstractmethod
    def list_for_order(self, order_id: str) -> list[Fill]:
        raise NotImplementedError
