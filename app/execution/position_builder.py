from __future__ import annotations

from app.core.models import Position
from .models import OrderRequest, OrderResult, OrderStatus


def position_from_fill(order: OrderRequest, result: OrderResult) -> Position:
    """Create a persisted position only from a confirmed fill."""
    if result.status is not OrderStatus.FILLED:
        raise ValueError("cannot create a position from a non-filled order")
    if result.filled_price is None:
        raise ValueError("filled order has no fill price")
    if result.symbol != order.symbol or result.order_id != order.order_id:
        raise ValueError("order/result identity mismatch")

    return Position(
        position_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        entry_price=result.filled_price,
        stop_loss=order.stop_loss,
        total_amount=result.filled_price * order.quantity,
        quantity=order.quantity,
        leverage=order.leverage,
        take_profit=order.take_profit,
        opened_at=result.filled_at or order.created_at,
    )
