from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from app.application.opportunity_pipeline import GatedOpportunity
from app.core.enums import PositionSide
from app.execution.models import OrderRequest, OrderType
from app.execution.validation import validate_order_request
from app.strategy.strategy_engine import StrategyState


@dataclass(frozen=True)
class PreparedOrder:
    opportunity: GatedOpportunity
    order: OrderRequest


def _stable_order_id(symbol: str, entry, stop_loss, target, side: PositionSide) -> str:
    key = f"{symbol}|{side.value}|{entry}|{stop_loss}|{target}"
    return f"prep-{uuid5(NAMESPACE_URL, key)}"


def prepare_order(
    opportunity: GatedOpportunity,
    *,
    order_type: OrderType = OrderType.LIMIT,
    order_id: str | None = None,
    created_at: datetime | None = None,
) -> PreparedOrder:
    """Convert one fully gated opportunity into an OrderRequest; never submit it."""
    signal = opportunity.signal
    if signal.state is not StrategyState.READY_FOR_RISK_REVIEW:
        raise ValueError("opportunity signal is not READY_FOR_RISK_REVIEW")
    if not opportunity.risk.approved or not opportunity.portfolio.approved:
        raise ValueError("opportunity must pass risk and portfolio gates")

    try:
        side = PositionSide(signal.direction)
    except ValueError as exc:
        raise ValueError(f"unsupported signal direction: {signal.direction}") from exc

    order = OrderRequest(
        order_id=order_id
        or _stable_order_id(
            signal.symbol, signal.entry, signal.stop_loss, signal.target, side
        ),
        symbol=signal.symbol,
        side=side,
        order_type=order_type,
        quantity=opportunity.risk.quantity,
        requested_price=signal.entry if order_type is OrderType.LIMIT else None,
        stop_loss=signal.stop_loss,
        take_profit=signal.target,
        leverage=opportunity.risk.leverage,
        created_at=created_at or datetime.now(timezone.utc),
        decision_snapshot=(
            opportunity.evidence.to_json() if opportunity.evidence is not None else None
        ),
    )
    valid, reason = validate_order_request(order)
    if not valid:
        raise ValueError(reason or "invalid prepared order")
    return PreparedOrder(opportunity=opportunity, order=order)


def prepare_orders(
    opportunities: Iterable[GatedOpportunity], *, order_type: OrderType = OrderType.LIMIT
) -> tuple[PreparedOrder, ...]:
    return tuple(prepare_order(item, order_type=order_type) for item in opportunities)
