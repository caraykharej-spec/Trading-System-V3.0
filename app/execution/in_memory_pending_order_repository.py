from __future__ import annotations

from .pending_order_repository import PendingOrderRepository
from .pending_orders import PendingOrder


class InMemoryPendingOrderRepository(PendingOrderRepository):
    def __init__(self, orders: list[PendingOrder] | None = None) -> None:
        self._orders = {item.order.order_id: item for item in (orders or [])}

    def list_active(self) -> list[PendingOrder]:
        return [order for order in self._orders.values() if order.is_active()]

    def save(self, order: PendingOrder) -> None:
        self._orders[order.order.order_id] = order

    def remove(self, order_id: str) -> None:
        self._orders.pop(order_id, None)
