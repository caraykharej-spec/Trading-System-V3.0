from __future__ import annotations

from typing import Optional

from .models import OrderRequest, OrderResult, OrderStatus
from .order_repository import OrderRepository


_ALLOWED_TRANSITIONS = {
    OrderStatus.PENDING: {OrderStatus.ACCEPTED, OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.ACCEPTED: {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.FILLED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.CANCELLED: set(),
}


class InMemoryOrderRepository(OrderRepository):
    """Deterministic order repository for tests and local runtime."""

    def __init__(self) -> None:
        self._requests: dict[str, OrderRequest] = {}
        self._results: dict[str, OrderResult] = {}

    def save_request(self, order: OrderRequest) -> None:
        if order.order_id in self._requests:
            raise ValueError(f"Order already exists: {order.order_id}")
        self._requests[order.order_id] = order

    def save_result(self, result: OrderResult) -> None:
        request = self._requests.get(result.order_id)
        if request is None:
            raise ValueError(f"Unknown order: {result.order_id}")
        existing = self._results.get(result.order_id)
        if existing is not None:
            if existing == result:
                return
            if result.status not in _ALLOWED_TRANSITIONS[existing.status]:
                raise ValueError(f"Invalid order transition: {existing.status} -> {result.status}")
        self._results[result.order_id] = result

    def get(self, order_id: str) -> Optional[tuple[OrderRequest, Optional[OrderResult]]]:
        request = self._requests.get(order_id)
        if request is None:
            return None
        return request, self._results.get(order_id)

    def exists(self, order_id: str) -> bool:
        return order_id in self._requests
