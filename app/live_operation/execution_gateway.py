from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.execution.models import OrderRequest, OrderResult, OrderStatus
from .activation import LiveActivationResult
from .exchange_connector import ExchangeProductionConnector


@dataclass(frozen=True)
class LiveExecutionResult:
    accepted: bool
    order_result: OrderResult
    gateway_reason: str
    processed_at: datetime


class LiveExecutionGateway:
    """Single guarded boundary for production order submission.

    The gateway is fail-closed and enforces activation, connector readiness,
    idempotency, and an explicit risk approval flag supplied by the caller.
    """

    def __init__(self, connector: ExchangeProductionConnector) -> None:
        self.connector = connector
        self._submitted_order_ids: set[str] = set()

    def submit(
        self,
        order: OrderRequest,
        *,
        activation: LiveActivationResult,
        risk_approved: bool,
    ) -> LiveExecutionResult:
        reason: str | None = None
        status = self.connector.status()
        if not activation.active:
            reason = f"live activation blocked: {activation.reason}"
        elif not risk_approved:
            reason = "live risk controller rejected order"
        elif not status.ready:
            reason = f"connector not ready: {status.reason or status.venue}"
        elif order.order_id in self._submitted_order_ids:
            reason = "duplicate order id blocked"

        if reason is not None:
            rejected = OrderResult(
                order_id=order.order_id,
                status=OrderStatus.REJECTED,
                symbol=order.symbol,
                reason=reason,
            )
            return LiveExecutionResult(
                accepted=False,
                order_result=rejected,
                gateway_reason=reason,
                processed_at=datetime.now(timezone.utc),
            )

        result = self.connector.submit_order(order)
        if result.status in {OrderStatus.ACCEPTED, OrderStatus.FILLED, OrderStatus.PENDING}:
            self._submitted_order_ids.add(order.order_id)
        return LiveExecutionResult(
            accepted=result.status != OrderStatus.REJECTED,
            order_result=result,
            gateway_reason=result.reason or "submitted to production connector",
            processed_at=datetime.now(timezone.utc),
        )
