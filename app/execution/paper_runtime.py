from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .atomic_execution import AtomicExecutionResult, AtomicExecutionService
from .execution_engine import ExecutionEngine
from .models import OrderRequest, OrderResult, OrderStatus
from .pending_order_repository import PendingOrderRepository
from .pending_orders import PendingOrder
from .order_repository import OrderRepository


@dataclass(frozen=True)
class PaperSubmissionResult:
    order: OrderRequest
    result: OrderResult
    atomic: AtomicExecutionResult | None = None
    pending: bool = False


class PaperTradingRuntime:
    """Complete PAPER order lifecycle: persist, execute, fill or persist pending."""

    def __init__(self, execution_engine: ExecutionEngine, order_repository: OrderRepository,
                 pending_repository: PendingOrderRepository, atomic_execution: AtomicExecutionService) -> None:
        self.execution_engine = execution_engine
        self.order_repository = order_repository
        self.pending_repository = pending_repository
        self.atomic_execution = atomic_execution

    def submit(self, order: OrderRequest) -> PaperSubmissionResult:
        if not order.order_id:
            raise ValueError("order_id is required")
        existing = self.order_repository.get(order.order_id)
        if existing is not None:
            stored_order, stored_result = existing
            if stored_order != order:
                raise ValueError(f"Conflicting order request: {order.order_id}")
            if stored_result is None:
                raise ValueError(f"Order already persisted without result: {order.order_id}")
            if stored_result.status is OrderStatus.ACCEPTED:
                self.pending_repository.save(PendingOrder(order=order, status=OrderStatus.ACCEPTED))
                return PaperSubmissionResult(order, stored_result, pending=True)
            return PaperSubmissionResult(order, stored_result, pending=False)

        self.order_repository.save_request(order)
        result = self.execution_engine.execute(order, mode="PAPER")
        if result.status is OrderStatus.FILLED:
            atomic = self.atomic_execution.apply_fill(
                order, result, fill_id=f"fill:{order.order_id}", commission=Decimal("0")
            )
            return PaperSubmissionResult(order, result, atomic=atomic)

        self.order_repository.save_result(result)
        if result.status is OrderStatus.ACCEPTED:
            self.pending_repository.save(PendingOrder(order=order, status=OrderStatus.ACCEPTED))
            return PaperSubmissionResult(order, result, pending=True)
        return PaperSubmissionResult(order, result, pending=False)
