from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .models import OrderRequest, OrderResult


class OrderRepository(ABC):
    """Persistence contract for the complete order lifecycle."""

    @abstractmethod
    def save_request(self, order: OrderRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_result(self, result: OrderResult) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, order_id: str) -> Optional[tuple[OrderRequest, Optional[OrderResult]]]:
        raise NotImplementedError

    @abstractmethod
    def exists(self, order_id: str) -> bool:
        raise NotImplementedError
