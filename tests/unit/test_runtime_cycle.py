from decimal import Decimal

from app.application.runtime_cycle import RuntimeCycleOrchestrator
from app.core.enums import PositionSide
from app.core.models import Position
from app.execution.atomic_execution import AtomicExecutionService
from app.execution.execution_engine import ExecutionEngine
from app.execution.in_memory_fill_repository import InMemoryFillRepository
from app.execution.in_memory_order_repository import InMemoryOrderRepository
from app.execution.in_memory_pending_order_repository import InMemoryPendingOrderRepository
from app.execution.models import OrderRequest, OrderType
from app.execution.paper_executor import PaperExecutor
from app.execution.paper_runtime import PaperTradingRuntime
from app.execution.pending_order_manager import PendingOrderManager
from app.portfolio.account import Account
from app.position.manager import ExitPolicy
from app.runtime.audit import AuditStatus, InMemoryCycleAuditRepository
from app.storage.repositories.in_memory_position_repository import InMemoryPositionRepository


def make_position() -> Position:
    return Position(
        "P-1",
        "BTC/USDT",
        PositionSide.LONG,
        Decimal("100"),
        Decimal("95"),
        Decimal("100"),
        Decimal("1"),
        Decimal("1"),
        Decimal("110"),
    )


def make_order() -> OrderRequest:
    return OrderRequest(
        "PAPER-1",
        "BTC/USDT",
        PositionSide.LONG,
        OrderType.MARKET,
        Decimal("1"),
        None,
        Decimal("95"),
        Decimal("110"),
        Decimal("1"),
    )


def make_paper_runtime(price=Decimal("100")):
    orders = InMemoryOrderRepository()
    pending = InMemoryPendingOrderRepository()
    positions = InMemoryPositionRepository()
    fills = InMemoryFillRepository()

    class Connection:
        def commit(self):
            pass

        def rollback(self):
            pass

    atomic = AtomicExecutionService(Connection(), orders, fills, positions)
    executor = PaperExecutor(lambda _: price)
    paper = PaperTradingRuntime(ExecutionEngine(executor), orders, pending, atomic)
    manager = PendingOrderManager(
        pending,
        executor,
        lambda o, r: atomic.apply_fill(o, r, fill_id=f"fill:{r.order_id}"),
    )
    return paper, manager, positions


def test_runtime_cycle_persists_completion_and_stop_out() -> None:
    positions = InMemoryPositionRepository([make_position()])
    audits = InMemoryCycleAuditRepository()
    runner = RuntimeCycleOrchestrator(
        positions,
        lambda _: Decimal("94"),
        Account(Decimal("1000")),
        audits,
    )
    result = runner.run("C-1")
    assert result.status.value == "COMPLETED"
    assert positions.list_open() == []
    assert result.stopped_positions == 1
    assert audits.get("C-1").status is AuditStatus.COMPLETED


def test_completed_cycle_is_idempotent() -> None:
    positions = InMemoryPositionRepository([make_position()])
    audits = InMemoryCycleAuditRepository()
    runner = RuntimeCycleOrchestrator(
        positions,
        lambda _: Decimal("94"),
        Account(Decimal("1000")),
        audits,
    )
    first = runner.run("C-2")
    equity_after_first = runner.account.equity
    second = runner.run("C-2")
    assert first.stopped_positions == 1
    assert second.stopped_positions == 1
    assert runner.account.equity == equity_after_first
    assert "idempotent replay" in second.notes[-1]


def test_failed_cycle_is_audited() -> None:
    audits = InMemoryCycleAuditRepository()
    runner = RuntimeCycleOrchestrator(
        InMemoryPositionRepository([make_position()]),
        lambda _: Decimal("0"),
        Account(Decimal("1000")),
        audits,
        exit_policy=ExitPolicy(),
    )
    try:
        runner.run("C-3")
    except ValueError:
        pass
    else:
        raise AssertionError("expected invalid live price")
    assert audits.get("C-3").status is AuditStatus.FAILED


def test_runtime_cycle_can_submit_selected_paper_order():
    paper, manager, positions = make_paper_runtime()
    audits = InMemoryCycleAuditRepository()
    runner = RuntimeCycleOrchestrator(
        positions,
        lambda _: Decimal("100"),
        Account(Decimal("1000")),
        audits,
        pending_order_manager=manager,
        paper_runtime=paper,
        selected_orders_provider=lambda: [make_order()],
    )
    result = runner.run("C-PAPER")
    assert result.status.value == "COMPLETED"
    assert len(positions.list_open()) == 1
    assert any("Paper order PAPER-1: FILLED" in note for note in result.notes)


def test_runtime_cycle_pending_limit_is_checked_before_new_submission():
    paper, manager, positions = make_paper_runtime(Decimal("110"))
    order = OrderRequest(
        "PENDING-1",
        "BTC/USDT",
        PositionSide.LONG,
        OrderType.LIMIT,
        Decimal("1"),
        Decimal("100"),
        Decimal("90"),
        Decimal("120"),
        Decimal("1"),
    )
    paper.submit(order)
    assert positions.list_open() == []
    manager.executor._live_price_provider = lambda _: Decimal("99")
    audits = InMemoryCycleAuditRepository()
    runner = RuntimeCycleOrchestrator(
        positions,
        lambda _: Decimal("99"),
        Account(Decimal("1000")),
        audits,
        pending_order_manager=manager,
    )
    result = runner.run("C-PENDING")
    assert len(positions.list_open()) == 1
    assert any("Pending order filled: PENDING-1" in note for note in result.notes)
