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

    def _market_price(self, symbol: str) -> Decimal | None:
        try:
            price = Decimal(str(self._live_price_provider(symbol)))
        except Exception:
            return None
        return price if price > 0 else None

    def _limit_result(self, order: OrderRequest, market_price: Decimal) -> OrderResult:
        if order.requested_price is None:
            return OrderResult(order.order_id, OrderStatus.REJECTED, order.symbol, reason="limit price required")
        if order.side.value == "LONG" and market_price > order.requested_price:
            return OrderResult(order.order_id, OrderStatus.ACCEPTED, order.symbol, reason="limit not fillable")
        if order.side.value == "SHORT" and market_price < order.requested_price:
            return OrderResult(order.order_id, OrderStatus.ACCEPTED, order.symbol, reason="limit not fillable")
        return OrderResult(
            order_id=order.order_id,
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            filled_price=order.requested_price,
            filled_at=utc_now(),
        )

    def check_limit(self, order: OrderRequest) -> OrderResult:
        """Check an existing limit order without changing order-id state."""
        valid, reason = validate_order_request(order)
        if not valid:
            return OrderResult(order.order_id, OrderStatus.REJECTED, order.symbol, reason=reason)
        if order.order_type is not OrderType.LIMIT:
            return OrderResult(order.order_id, OrderStatus.REJECTED, order.symbol, reason="not a limit order")
        market_price = self._market_price(order.symbol)
        if market_price is None:
            return OrderResult(order.order_id, OrderStatus.REJECTED, order.symbol, reason="invalid live price")
        return self._limit_result(order, market_price)

    def submit(self, order: OrderRequest) -> OrderResult:
        valid, reason = validate_order_request(order)
        if not valid:
            return OrderResult(order.order_id, OrderStatus.REJECTED, order.symbol, reason=reason)
        if order.order_id in self._orders:
            return OrderResult(order.order_id, OrderStatus.REJECTED, order.symbol, reason="duplicate order_id")

        market_price = self._market_price(order.symbol)
        if market_price is None:
            return OrderResult(order.order_id, OrderStatus.REJECTED, order.symbol, reason="invalid live price")

        if order.order_type is OrderType.LIMIT:
            result = self._limit_result(order, market_price)
            if result.status is OrderStatus.ACCEPTED:
                return result
        else:
            result = OrderResult(
                order_id=order.order_id,
                status=OrderStatus.FILLED,
                symbol=order.symbol,
                filled_price=market_price,
                filled_at=utc_now(),
            )

        self._orders.add(order.order_id)
        return result
