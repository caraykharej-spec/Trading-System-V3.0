from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import sqlite3

from app.core.enums import PositionSide
from .models import OrderRequest, OrderStatus, OrderType
from .pending_order_repository import PendingOrderRepository
from .pending_orders import PendingOrder


class SQLitePendingOrderRepository(PendingOrderRepository):
    """Durable persistence for accepted, not-yet-filled paper orders."""

    def __init__(self, connection: sqlite3.Connection, *, auto_commit: bool = True) -> None:
        self.connection = connection
        self.auto_commit = auto_commit

    def list_active(self) -> list[PendingOrder]:
        rows = self.connection.execute(
            "SELECT order_id, accepted_at, updated_at, cancel_reason, rejection_reason "
            "FROM pending_orders WHERE status = ? ORDER BY accepted_at, order_id",
            (OrderStatus.ACCEPTED.value,),
        ).fetchall()
        result: list[PendingOrder] = []
        for row in rows:
            order_row = self.connection.execute(
                """SELECT order_id, symbol, side, order_type, quantity, requested_price,
                   stop_loss, take_profit, leverage, created_at, decision_snapshot
                   FROM orders WHERE order_id = ?""",
                (row[0],),
            ).fetchone()
            if order_row is None:
                raise ValueError(f"Pending order references missing order: {row[0]}")
            order = OrderRequest(
                order_id=str(order_row[0]),
                symbol=str(order_row[1]),
                side=PositionSide(str(order_row[2])),
                order_type=OrderType(str(order_row[3])),
                quantity=Decimal(str(order_row[4])),
                requested_price=(
                    Decimal(str(order_row[5])) if order_row[5] is not None else None
                ),
                stop_loss=Decimal(str(order_row[6])),
                take_profit=(
                    Decimal(str(order_row[7])) if order_row[7] is not None else None
                ),
                leverage=Decimal(str(order_row[8])),
                created_at=datetime.fromisoformat(str(order_row[9])),
                decision_snapshot=(
                    str(order_row[10]) if order_row[10] is not None else None
                ),
            )
            result.append(
                PendingOrder(
                    order=order,
                    status=OrderStatus.ACCEPTED,
                    accepted_at=datetime.fromisoformat(str(row[1])),
                    updated_at=datetime.fromisoformat(str(row[2])),
                    cancel_reason=row[3],
                    rejection_reason=row[4],
                )
            )
        return result

    def save(self, order: PendingOrder) -> None:
        if order.status not in {
            OrderStatus.ACCEPTED,
            OrderStatus.REJECTED,
            OrderStatus.CANCELLED,
        }:
            raise ValueError(
                "pending repository accepts only accepted/rejected/cancelled states"
            )
        exists = self.connection.execute(
            "SELECT 1 FROM orders WHERE order_id = ?", (order.order.order_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"Unknown order: {order.order.order_id}")
        self.connection.execute(
            """INSERT INTO pending_orders
               (order_id, status, accepted_at, updated_at, cancel_reason, rejection_reason)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(order_id) DO UPDATE SET status=excluded.status,
                 updated_at=excluded.updated_at, cancel_reason=excluded.cancel_reason,
                 rejection_reason=excluded.rejection_reason""",
            (
                order.order.order_id,
                order.status.value,
                order.accepted_at.isoformat(),
                order.updated_at.isoformat(),
                order.cancel_reason,
                order.rejection_reason,
            ),
        )
        if self.auto_commit:
            self.connection.commit()

    def remove(self, order_id: str) -> None:
        self.connection.execute("DELETE FROM pending_orders WHERE order_id = ?", (order_id,))
        if self.auto_commit:
            self.connection.commit()
