from __future__ import annotations

from decimal import Decimal
from typing import Callable

from .models import OrderRequest, OrderResult, OrderStatus, OrderType, utc_now
from .validation import validate_order_request

LivePriceProvider = Callable[[str], Decimal]


class PaperExecutor:
    """Deterministic paper executor. It never sends orders to a broker."""

    def __init__(self, live_price_provider: LivePriceProvider) -> None:
        self._live_price_provider = live_price_provider
        self._orders: set[str] = set()

    def submit(self, order: OrderRequest) -> OrderResult:
        valid, reason = validate_order_request(order)
        if not valid:
            return OrderResult(order.order_id, OrderStatus.REJECTED, order.symbol, reason=reason)
        if order.order_id in self._orders:
            return OrderResult(order.order_id, OrderStatus.REJECTED, order.symbol, reason="duplicate order_id")

        self._orders.add(order.order_id)
        market_price = Decimal(str(self._live_price_provider(order.symbol)))
        if market_price <= 0:
            return OrderResult(order.order_id, OrderStatus.REJECTED, order.symbol, reason="invalid live price")

        if order.order_type is OrderType.LIMIT:
            if order.side.value == "LONG" and market_price > order.requested_price:
                return OrderResult(order.order_id, OrderStatus.ACCEPTED, order.symbol, reason="limit not fillable")
            if order.side.value == "SHORT" and market_price < order.requested_price:
                return OrderResult(order.order_id, OrderStatus.ACCEPTED, order.symbol, reason="limit not fillable")
            fill_price = order.requested_price
        else:
            fill_price = market_price

        return OrderResult(
            order_id=order.order_id,
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            filled_price=fill_price,
            filled_at=utc_now(),
        )
