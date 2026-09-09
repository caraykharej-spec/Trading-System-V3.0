from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import sqlite3

from app.core.enums import PositionSide
from app.execution.models import OrderRequest, OrderResult, OrderStatus, OrderType
from app.execution.order_repository import OrderRepository


_ALLOWED_TRANSITIONS = {
    OrderStatus.PENDING: {OrderStatus.ACCEPTED, OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.ACCEPTED: {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.FILLED: set(), OrderStatus.REJECTED: set(), OrderStatus.CANCELLED: set(),
}


class SQLiteOrderRepository(OrderRepository):
    """SQLite persistence for the complete order request/result lifecycle."""

    def __init__(self, connection: sqlite3.Connection, *, auto_commit: bool = True) -> None:
        self.connection = connection
        self.auto_commit = auto_commit

    def save_request(self, order: OrderRequest) -> None:
        self.connection.execute(
            """INSERT INTO orders (order_id, symbol, side, order_type, quantity, requested_price,
               stop_loss, take_profit, leverage, created_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (order.order_id, order.symbol, order.side.value, order.order_type.value,
             str(order.quantity), str(order.requested_price) if order.requested_price is not None else None,
             str(order.stop_loss), str(order.take_profit) if order.take_profit is not None else None,
             str(order.leverage), order.created_at.isoformat(), OrderStatus.PENDING.value),
        )
        if self.auto_commit:
            self.connection.commit()

    def save_result(self, result: OrderResult) -> None:
        row = self.connection.execute(
            "SELECT status, symbol, filled_price, reason, filled_at FROM orders WHERE order_id = ?",
            (result.order_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown order: {result.order_id}")
        current = OrderStatus(str(row[0]))
        if current is not result.status and result.status not in _ALLOWED_TRANSITIONS[current]:
            raise ValueError(f"Invalid order transition: {current} -> {result.status}")
        incoming = (result.symbol, str(result.filled_price) if result.filled_price is not None else None,
                    result.reason, result.filled_at.isoformat() if result.filled_at else None)
        existing = (row[1], row[2], row[3], row[4])
        if current is result.status:
            if existing != incoming:
                raise ValueError(f"Conflicting result for order: {result.order_id}")
            return
        self.connection.execute(
            """UPDATE orders SET status = ?, symbol = ?, filled_price = ?, reason = ?, filled_at = ?
               WHERE order_id = ?""",
            (result.status.value, result.symbol,
             str(result.filled_price) if result.filled_price is not None else None,
             result.reason, result.filled_at.isoformat() if result.filled_at else None, result.order_id),
        )
        if self.auto_commit:
            self.connection.commit()

    def get(self, order_id: str) -> tuple[OrderRequest, OrderResult | None] | None:
        row = self.connection.execute(
            """SELECT order_id, symbol, side, order_type, quantity, requested_price,
               stop_loss, take_profit, leverage, created_at, status, filled_price, reason, filled_at
               FROM orders WHERE order_id = ?""", (order_id,)
        ).fetchone()
        if row is None:
            return None
        request = OrderRequest(
            order_id=str(row[0]), symbol=str(row[1]), side=PositionSide(str(row[2])),
            order_type=OrderType(str(row[3])), quantity=Decimal(str(row[4])),
            requested_price=Decimal(str(row[5])) if row[5] is not None else None,
            stop_loss=Decimal(str(row[6])), take_profit=Decimal(str(row[7])) if row[7] is not None else None,
            leverage=Decimal(str(row[8])), created_at=datetime.fromisoformat(str(row[9])),
        )
        result = None if row[10] == OrderStatus.PENDING.value else OrderResult(
            order_id=str(row[0]), status=OrderStatus(str(row[10])), symbol=str(row[1]),
            filled_price=Decimal(str(row[11])) if row[11] is not None else None,
            reason=str(row[12]) if row[12] is not None else None,
            filled_at=datetime.fromisoformat(str(row[13])) if row[13] else None,
        )
        return request, result

    def exists(self, order_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone() is not None
