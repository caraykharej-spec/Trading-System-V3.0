from __future__ import annotations

from decimal import Decimal

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
    if order.quantity <= 0 or order.leverage <= 0:
        raise ValueError("quantity and leverage must be positive")

    notional = result.filled_price * order.quantity
    collateral = notional / order.leverage
    if collateral <= Decimal("0"):
        raise ValueError("calculated position amount must be positive")

    return Position(
        position_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        entry_price=result.filled_price,
        stop_loss=order.stop_loss,
        total_amount=collateral,
        quantity=order.quantity,
        leverage=order.leverage,
        take_profit=order.take_profit,
        opened_at=result.filled_at or order.created_at,
    )
