from __future__ import annotations

from abc import ABC, abstractmethod

from .pending_orders import PendingOrder


class PendingOrderRepository(ABC):
    """Persistence contract for accepted but not-yet-filled orders."""

    @abstractmethod
    def list_active(self) -> list[PendingOrder]:
        raise NotImplementedError

    @abstractmethod
    def save(self, order: PendingOrder) -> None:
        raise NotImplementedError

    @abstractmethod
    def remove(self, order_id: str) -> None:
        raise NotImplementedError
