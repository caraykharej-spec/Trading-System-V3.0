from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.core.models import Position
from .fills import Fill
from .models import OrderRequest, OrderResult, OrderStatus
from .position_builder import position_from_fill


class TransactionConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[object, ...] = ...) -> object: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class PositionWriter(Protocol):
    def save(self, position: Position) -> None: ...


class FillWriter(Protocol):
    def save(self, fill: Fill) -> None: ...


@dataclass(frozen=True)
class AtomicExecutionResult:
    order_id: str
    position_id: str | None
    status: OrderStatus
    created_position: bool


class AtomicExecutionService:
    """Coordinates fill persistence and position creation as one local transaction."""

    def __init__(
        self,
        connection: TransactionConnection,
        fill_writer: FillWriter,
        position_writer: PositionWriter,
    ) -> None:
        self.connection = connection
        self.fill_writer = fill_writer
        self.position_writer = position_writer

    def apply_fill(
        self,
        order: OrderRequest,
        result: OrderResult,
        *,
        fill_id: str,
        commission: Decimal = Decimal("0"),
    ) -> AtomicExecutionResult:
        if result.status is not OrderStatus.FILLED:
            raise ValueError("atomic fill application requires a FILLED order result")
        if result.filled_price is None:
            raise ValueError("filled order has no fill price")
        if commission < 0:
            raise ValueError("commission cannot be negative")

        position = position_from_fill(order, result)
        fill = Fill(
            fill_id=fill_id,
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=result.filled_price,
            commission=commission,
            filled_at=result.filled_at,
        )

        try:
            self.fill_writer.save(fill)
            self.position_writer.save(position)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        return AtomicExecutionResult(
            order_id=order.order_id,
            position_id=position.position_id,
            status=result.status,
            created_position=True,
        )
