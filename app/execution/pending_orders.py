from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

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
    cancel_reason: Optional[str] = None
    rejection_reason: Optional[str] = None

    def cancel(self, reason: str | None = None) -> None:
        self.status = OrderStatus.CANCELLED
        self.updated_at = utc_now()
        self.cancel_reason = reason

    def reject(self, reason: str | None = None) -> None:
        self.status = OrderStatus.REJECTED
        self.updated_at = utc_now()
        self.rejection_reason = reason

    def is_active(self) -> bool:
        return self.status is OrderStatus.ACCEPTED
