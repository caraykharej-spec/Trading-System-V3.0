from __future__ import annotations

from decimal import Decimal

from .models import OrderRequest, OrderType


def validate_order_request(order: OrderRequest) -> tuple[bool, str | None]:
    if not order.order_id.strip():
        return False, "order_id is required"
    if not order.symbol.strip():
        return False, "symbol is required"
    if order.quantity <= 0:
        return False, "quantity must be positive"
    if order.leverage <= 0:
        return False, "leverage must be positive"
    if order.stop_loss <= 0:
        return False, "stop_loss must be positive"
    if order.order_type is OrderType.LIMIT:
        if order.requested_price is None or order.requested_price <= 0:
            return False, "limit order requires a positive requested_price"
    elif order.requested_price is not None and order.requested_price <= 0:
        return False, "requested_price must be positive when provided"
    if order.take_profit is not None and order.take_profit <= 0:
        return False, "take_profit must be positive"
    if order.take_profit is not None:
        if order.side.value == "LONG" and order.take_profit <= order.stop_loss:
            return False, "long take_profit must be above stop_loss"
        if order.side.value == "SHORT" and order.take_profit >= order.stop_loss:
            return False, "short take_profit must be below stop_loss"
    return True, None
