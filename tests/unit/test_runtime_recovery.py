from datetime import datetime, timezone
from decimal import Decimal

from app.core.enums import PositionSide
from app.execution.models import OrderRequest, OrderStatus, OrderType
from app.execution.in_memory_pending_order_repository import InMemoryPendingOrderRepository
from app.execution.pending_order_manager import PendingOrderManager
from app.execution.pending_orders import PendingOrder
from app.execution.paper_executor import PaperExecutor
from app.runtime.audit import AuditStatus, CycleAudit, InMemoryCycleAuditRepository
from app.runtime.idempotency import IdempotencyGuard, InMemoryOperationRepository


def make_limit(order_id: str) -> OrderRequest:
    return OrderRequest(
        order_id=order_id,
        symbol="BTC/USDT",
        side=PositionSide.LONG,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        requested_price=Decimal("100"),
        stop_loss=Decimal("90"),
        take_profit=Decimal("120"),
        leverage=Decimal("1"),
    )


def test_pending_order_can_recover_and_fill() -> None:
    repository = InMemoryPendingOrderRepository([PendingOrder(make_limit("O-1"))])
    executor = PaperExecutor(lambda _: Decimal("99"))
    result = PendingOrderManager(repository, executor).check()

    assert result.checked == 1
    assert len(result.filled) == 1
    assert result.filled[0].status is OrderStatus.FILLED
    assert repository.list_active() == []


def test_cycle_audit_latest_is_deterministic() -> None:
    repository = InMemoryCycleAuditRepository()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    repository.save(CycleAudit("C-1", AuditStatus.COMPLETED, now))
    repository.save(CycleAudit("C-2", AuditStatus.STARTED, now.replace(minute=1)))
    assert repository.latest().cycle_id == "C-2"


def test_idempotency_reuses_existing_result() -> None:
    guard = IdempotencyGuard(InMemoryOperationRepository())
    guard.record("OP-1", "RESULT-1")
    assert guard.existing_result("OP-1") == "RESULT-1"
    guard.record("OP-1", "RESULT-1")


def test_idempotency_rejects_different_retry_result() -> None:
    guard = IdempotencyGuard(InMemoryOperationRepository())
    guard.record("OP-1", "RESULT-1")
    try:
        guard.record("OP-1", "RESULT-2")
    except ValueError:
        pass
    else:
        raise AssertionError("expected conflicting retry to fail")
