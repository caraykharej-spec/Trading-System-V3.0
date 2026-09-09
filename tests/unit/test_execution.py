from decimal import Decimal

from app.core.enums import PositionSide
from app.execution.execution_engine import ExecutionEngine
from app.execution.models import OrderRequest, OrderStatus, OrderType
from app.execution.paper_executor import PaperExecutor
from app.execution.validation import validate_order_request


def order(**kwargs):
    values = dict(
        order_id="o1",
        symbol="BTC/USD",
        side=PositionSide.LONG,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        requested_price=None,
        stop_loss=Decimal("90"),
        take_profit=Decimal("120"),
        leverage=Decimal("1"),
    )
    values.update(kwargs)
    return OrderRequest(**values)


def test_invalid_order_rejected():
    valid, reason = validate_order_request(order(quantity=Decimal("0")))
    assert not valid
    assert reason


def test_paper_market_order_fills_at_live_price():
    executor = PaperExecutor(lambda _: Decimal("100"))
    result = executor.submit(order())
    assert result.status is OrderStatus.FILLED
    assert result.filled_price == Decimal("100")


def test_duplicate_order_rejected():
    executor = PaperExecutor(lambda _: Decimal("100"))
    executor.submit(order())
    result = executor.submit(order())
    assert result.status is OrderStatus.REJECTED
    assert result.reason == "duplicate order_id"


def test_disabled_mode_rejected():
    executor = PaperExecutor(lambda _: Decimal("100"))
    engine = ExecutionEngine(executor)
    result = engine.execute(order(), mode="LIVE")
    assert result.status is OrderStatus.REJECTED


def test_short_tp_relationship():
    valid, reason = validate_order_request(
        order(side=PositionSide.SHORT, stop_loss=Decimal("110"), take_profit=Decimal("90"))
    )
    assert valid, reason
