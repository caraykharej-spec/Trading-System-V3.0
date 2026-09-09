from decimal import Decimal

from app.core.enums import PositionSide
from app.execution.models import OrderRequest, OrderStatus, OrderType
from app.execution.paper_executor import PaperExecutor
from app.execution.pending_order_manager import PendingOrderManager
from app.execution.pending_orders import PendingOrder
from app.execution.in_memory_pending_order_repository import InMemoryPendingOrderRepository


def make_order() -> OrderRequest:
    return OrderRequest(
        order_id="L-12",
        symbol="BTC/USDT",
        side=PositionSide.LONG,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        requested_price=Decimal("100"),
        stop_loss=Decimal("90"),
        take_profit=Decimal("120"),
    )


def test_pending_limit_survives_unfilled_check() -> None:
    repo = InMemoryPendingOrderRepository([PendingOrder(make_order())])
    executor = PaperExecutor(lambda _: Decimal("110"))
    result = PendingOrderManager(repo, executor).check()

    assert result.checked == 1
    assert result.filled == ()
    assert len(repo.list_active()) == 1


def test_pending_limit_fills_without_duplicate_order_rejection() -> None:
    repo = InMemoryPendingOrderRepository([PendingOrder(make_order())])
    executor = PaperExecutor(lambda _: Decimal("99"))
    result = PendingOrderManager(repo, executor).check()

    assert result.checked == 1
    assert len(result.filled) == 1
    assert result.filled[0].status is OrderStatus.FILLED
    assert result.filled[0].filled_price == Decimal("100")
    assert repo.list_active() == []
