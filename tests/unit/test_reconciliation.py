from datetime import datetime, timezone
from decimal import Decimal

from app.core.enums import PositionSide
from app.execution.in_memory_fill_repository import InMemoryFillRepository
from app.execution.in_memory_order_repository import InMemoryOrderRepository
from app.execution.models import OrderRequest, OrderResult, OrderStatus, OrderType
from app.recovery.reconciliation import RecoveryReconciler
from app.storage.repositories.in_memory_position_repository import InMemoryPositionRepository
from app.execution.fills import Fill


def order(order_id="o1"):
    return OrderRequest(order_id, "BTC/USD", PositionSide.LONG, OrderType.MARKET,
        Decimal("0.01"), None, Decimal("70000"), Decimal("90000"), Decimal("7"),
        datetime.now(timezone.utc))


def result(order_id="o1"):
    return OrderResult(order_id, OrderStatus.FILLED, "BTC/USD", Decimal("80000"), None,
        datetime.now(timezone.utc))


def test_reconciler_repairs_filled_order_missing_position():
    orders = InMemoryOrderRepository()
    fills = InMemoryFillRepository()
    positions = InMemoryPositionRepository()
    o = order()
    r = result()
    orders.save_request(o)
    orders.save_result(r)
    fills.save(Fill("f1", "o1", "BTC/USD", PositionSide.LONG, Decimal("0.01"), Decimal("80000"), Decimal("0"), r.filled_at))

    outcome = RecoveryReconciler(orders, fills, positions).reconcile(["o1"])
    assert outcome.repaired_positions == 1
    assert len(positions.list_open()) == 1


def test_reconciler_is_idempotent():
    orders = InMemoryOrderRepository()
    fills = InMemoryFillRepository()
    positions = InMemoryPositionRepository()
    o = order(); r = result()
    orders.save_request(o); orders.save_result(r)
    fills.save(Fill("f1", "o1", "BTC/USD", PositionSide.LONG, Decimal("0.01"), Decimal("80000"), Decimal("0"), r.filled_at))
    reconciler = RecoveryReconciler(orders, fills, positions)
    assert reconciler.reconcile(["o1"]).repaired_positions == 1
    assert reconciler.reconcile(["o1"]).repaired_positions == 0
    assert len(positions.list_open()) == 1


def test_reconciler_reports_filled_without_fill():
    orders = InMemoryOrderRepository()
    positions = InMemoryPositionRepository()
    o = order(); orders.save_request(o); orders.save_result(result())
    outcome = RecoveryReconciler(orders, InMemoryFillRepository(), positions).reconcile(["o1"])
    assert outcome.repaired_positions == 0
    assert outcome.issues[0].kind == "FILLED_WITHOUT_FILL"
