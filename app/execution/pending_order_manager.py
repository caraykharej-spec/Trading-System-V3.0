from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import OrderRequest, OrderResult, OrderStatus, OrderType
from .paper_executor import PaperExecutor
from .pending_order_repository import PendingOrderRepository


@dataclass(frozen=True)
class PendingOrderUpdate:
    checked: int
    filled: tuple[OrderResult, ...]


class PendingOrderManager:
    """Rechecks accepted limit orders without resubmitting them as new orders."""

    def __init__(
        self,
        repository: PendingOrderRepository,
        executor: PaperExecutor,
        fill_handler: Callable[[OrderRequest, OrderResult], None] | None = None,
    ) -> None:
        self.repository = repository
        self.executor = executor
        self.fill_handler = fill_handler

    def check(self) -> PendingOrderUpdate:
        filled: list[OrderResult] = []
        active = self.repository.list_active()
        for pending in active:
            if pending.order.order_type is not OrderType.LIMIT:
                pending.reject("pending manager only supports limit orders")
                self.repository.save(pending)
                continue

            result = self.executor.check_limit(pending.order)
            if result.status is OrderStatus.FILLED:
                if self.fill_handler is not None:
                    self.fill_handler(pending.order, result)
                filled.append(result)
                self.repository.remove(pending.order.order_id)
            elif result.status is OrderStatus.REJECTED:
                pending.reject(result.reason)
                self.repository.save(pending)
            else:
                self.repository.save(pending)
        return PendingOrderUpdate(checked=len(active), filled=tuple(filled))
