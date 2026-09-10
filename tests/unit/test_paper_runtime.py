from decimal import Decimal

from app.core.enums import PositionSide
from app.execution.atomic_execution import AtomicExecutionService
from app.execution.execution_engine import ExecutionEngine
from app.execution.fills import Fill
from app.execution.in_memory_fill_repository import InMemoryFillRepository
from app.execution.in_memory_order_repository import InMemoryOrderRepository
from app.execution.in_memory_pending_order_repository import InMemoryPendingOrderRepository
from app.execution.models import OrderRequest, OrderResult, OrderStatus, OrderType
from app.execution.paper_executor import PaperExecutor
from app.execution.paper_runtime import PaperTradingRuntime
from app.execution.pending_orders import PendingOrder
from app.storage.database import connect
from app.storage.repositories.in_memory_position_repository import InMemoryPositionRepository
from app.storage.repositories.sqlite_order_repository import SQLiteOrderRepository
from app.storage.repositories.sqlite_pending_order_repository import SQLitePendingOrderRepository


def make_order(order_id="p-1", order_type=OrderType.MARKET, price=None):
    return OrderRequest(order_id=order_id, symbol="BTC/USD", side=PositionSide.LONG,
                        order_type=order_type, quantity=Decimal("1"), requested_price=price,
                        stop_loss=Decimal("90"), take_profit=Decimal("120"), leverage=Decimal("2"))


def make_runtime(price):
    orders = InMemoryOrderRepository()
    pending = InMemoryPendingOrderRepository()
    positions = InMemoryPositionRepository()
    fills = InMemoryFillRepository()
    class Connection:
        def commit(self): pass
        def rollback(self): pass
    atomic = AtomicExecutionService(Connection(), orders, fills, positions)
    executor = PaperExecutor(lambda _: price)
    return PaperTradingRuntime(ExecutionEngine(executor), orders, pending, atomic), orders, pending, positions


def test_market_order_fills_and_creates_position():
    runtime, orders, pending, positions = make_runtime(Decimal("100"))
    result = runtime.submit(make_order())
    assert result.result.status is OrderStatus.FILLED
    assert result.atomic is not None
    position = positions.list_open()[0]
    assert position.entry_price == Decimal("100")
    assert position.total_amount == Decimal("50")
    assert pending.list_active() == []
    assert orders.get("p-1")[1].status is OrderStatus.FILLED


def test_unfilled_limit_is_persisted_as_pending():
    runtime, orders, pending, positions = make_runtime(Decimal("110"))
    result = runtime.submit(make_order("p-2", OrderType.LIMIT, Decimal("100")))
    assert result.pending is True
    assert result.result.status is OrderStatus.ACCEPTED
    assert len(pending.list_active()) == 1
    assert positions.list_open() == []
    assert orders.get("p-2")[1].status is OrderStatus.ACCEPTED


def test_repeated_submission_is_idempotent():
    runtime, _, _, positions = make_runtime(Decimal("100"))
    order = make_order("p-3")
    first = runtime.submit(order)
    second = runtime.submit(order)
    assert first.result == second.result
    assert len(positions.list_open()) == 1


def test_sqlite_pending_order_survives_restart(tmp_path):
    path = tmp_path / "paper.db"
    conn = connect(path)
    orders = SQLiteOrderRepository(conn)
    pending = SQLitePendingOrderRepository(conn)
    order = make_order("p-4", OrderType.LIMIT, Decimal("100"))
    orders.save_request(order)
    orders.save_result(OrderResult("p-4", OrderStatus.ACCEPTED, "BTC/USD", reason="limit not fillable"))
    pending.save(PendingOrder(order))
    conn.close()
    conn2 = connect(path)
    restored = SQLitePendingOrderRepository(conn2).list_active()
    assert len(restored) == 1
    assert restored[0].order.order_id == "p-4"
    conn2.close()
