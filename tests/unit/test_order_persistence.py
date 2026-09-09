from datetime import datetime, timezone
from decimal import Decimal
import sqlite3

from app.core.enums import PositionSide
from app.execution.fills import Fill
from app.execution.in_memory_order_repository import InMemoryOrderRepository
from app.execution.models import OrderRequest, OrderResult, OrderStatus, OrderType
from app.storage.database import connect
from app.storage.repositories.sqlite_fill_repository import SQLiteFillRepository
from app.storage.repositories.sqlite_order_repository import SQLiteOrderRepository


def make_order(order_id: str = "ord-1") -> OrderRequest:
    return OrderRequest(
        order_id=order_id,
        symbol="BTC/USD",
        side=PositionSide.LONG,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.01"),
        requested_price=Decimal("100"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        leverage=Decimal("2"),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def filled_result(order_id: str = "ord-1") -> OrderResult:
    return OrderResult(
        order_id=order_id,
        status=OrderStatus.FILLED,
        symbol="BTC/USD",
        filled_price=Decimal("100.5"),
        filled_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
    )


def test_in_memory_order_lifecycle_allows_accepted_to_filled() -> None:
    repository = InMemoryOrderRepository()
    order = make_order()
    repository.save_request(order)
    repository.save_result(
        OrderResult(order_id=order.order_id, status=OrderStatus.ACCEPTED, symbol=order.symbol, reason="limit not fillable")
    )
    repository.save_result(filled_result())
    saved = repository.get(order.order_id)
    assert saved is not None
    assert saved[1] == filled_result()


def test_sqlite_order_and_fill_survive_reopen(tmp_path) -> None:
    path = tmp_path / "trading.db"
    connection = connect(path)
    orders = SQLiteOrderRepository(connection)
    fills = SQLiteFillRepository(connection)
    order = make_order()
    result = filled_result()

    orders.save_request(order)
    orders.save_result(result)
    fill = Fill(
        fill_id="fill-1",
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        price=result.filled_price,
        commission=Decimal("0.10"),
        filled_at=result.filled_at,
    )
    fills.save(fill)
    connection.close()

    reopened = connect(path)
    saved_order = SQLiteOrderRepository(reopened).get(order.order_id)
    saved_fills = SQLiteFillRepository(reopened).list_for_order(order.order_id)
    assert saved_order is not None
    assert saved_order[0] == order
    assert saved_order[1] == result
    assert saved_fills == [fill]
    reopened.close()


def test_sqlite_fill_is_idempotent_but_rejects_conflict(tmp_path) -> None:
    connection = connect(tmp_path / "trading.db")
    orders = SQLiteOrderRepository(connection)
    fills = SQLiteFillRepository(connection)
    order = make_order()
    orders.save_request(order)
    orders.save_result(filled_result())
    fill = Fill("fill-1", order.order_id, order.symbol, order.side, order.quantity, Decimal("100"))
    fills.save(fill)
    fills.save(fill)
    conflicting = Fill("fill-1", order.order_id, order.symbol, order.side, order.quantity, Decimal("101"))
    try:
        fills.save(conflicting)
    except ValueError:
        pass
    else:
        raise AssertionError("Conflicting fill must be rejected")
    connection.close()
