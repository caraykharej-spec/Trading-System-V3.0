from __future__ import annotations

from typing import Optional

from .models import OrderRequest, OrderResult
from .order_repository import OrderRepository


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
        if result.order_id not in self._requests:
            raise ValueError(f"Unknown order: {result.order_id}")
        existing = self._results.get(result.order_id)
        if existing is not None and existing != result:
            raise ValueError(f"Conflicting result for order: {result.order_id}")
        self._results[result.order_id] = result

    def get(self, order_id: str) -> Optional[tuple[OrderRequest, Optional[OrderResult]]]:
        request = self._requests.get(order_id)
        if request is None:
            return None
        return request, self._results.get(order_id)

    def exists(self, order_id: str) -> bool:
        return order_id in self._requests
