from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

from app.execution.models import OrderRequest
from app.risk.risk_math import candidate_risk_amount


PriceProvider = Callable[[str], Decimal]


@dataclass(frozen=True)
class PendingRiskReservation:
    total_risk: Decimal
    order_risk: dict[str, Decimal]
    unresolved_order_ids: tuple[str, ...]


def reserve_pending_order_risk(
    orders: Iterable[OrderRequest],
    *,
    market_price_provider: PriceProvider | None = None,
) -> PendingRiskReservation:
    """Reserve worst structural SL risk for accepted/pending paper orders.

    LIMIT orders use their requested price. MARKET orders require an explicit
    reference-price provider; unresolved market orders are surfaced rather than
    silently assigned zero risk.
    """
    reservations: dict[str, Decimal] = {}
    unresolved: list[str] = []

    for order in orders:
        if order.leverage <= 0 or order.quantity <= 0 or order.stop_loss <= 0:
            raise ValueError(f"invalid pending order risk inputs: {order.order_id}")
        entry = order.requested_price
        if entry is None:
            if market_price_provider is None:
                unresolved.append(order.order_id)
                continue
            entry = Decimal(str(market_price_provider(order.symbol)))
        if entry <= 0:
            raise ValueError(f"invalid pending entry price: {order.order_id}")

        collateral = entry * order.quantity / order.leverage
        reservations[order.order_id] = candidate_risk_amount(
            total_amount=collateral,
            entry=entry,
            stop_loss=order.stop_loss,
            leverage=order.leverage,
        )

    return PendingRiskReservation(
        total_risk=sum(reservations.values(), Decimal("0")),
        order_risk=reservations,
        unresolved_order_ids=tuple(unresolved),
    )
