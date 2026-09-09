from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from .models import OrderRequest, OrderStatus


UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class PendingOrder:
    order: OrderRequest
    status: OrderStatus = OrderStatus.ACCEPTED
    accepted_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def cancel(self, reason: str | None = None) -> None:
        self.status = OrderStatus.CANCELLED
        self.updated_at = utc_now()
        self.cancel_reason = reason

    def is_active(self) -> bool:
        return self.status is OrderStatus.ACCEPTED
