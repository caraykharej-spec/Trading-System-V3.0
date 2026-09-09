from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.enums import PositionSide

from .models import OrderRequest, OrderResult, OrderStatus, OrderType
from .paper_executor import PaperExecutor
from .pending_order_repository import PendingOrderRepository
from .pending_orders import PendingOrder


@dataclass(frozen=True)
class PendingOrderUpdate:
    checked: int
    filled: tuple[OrderResult, ...]


class PendingOrderManager:
    """Rechecks accepted limit orders after restart and converts fills to results."""

    def __init__(self, repository: PendingOrderRepository, executor: PaperExecutor) -> None:
        self.repository = repository
        self.executor = executor

    def check(self) -> PendingOrderUpdate:
        filled: list[OrderResult] = []
        active = self.repository.list_active()
        for pending in active:
            result = self.executor.submit(pending.order)
            if result.status is OrderStatus.FILLED:
                filled.append(result)
                self.repository.remove(pending.order.order_id)
            elif result.status is OrderStatus.REJECTED:
                pending.status = OrderStatus.REJECTED
                pending.updated_at = result.filled_at or pending.updated_at
                self.repository.save(pending)
            else:
                self.repository.save(pending)
        return PendingOrderUpdate(checked=len(active), filled=tuple(filled))
