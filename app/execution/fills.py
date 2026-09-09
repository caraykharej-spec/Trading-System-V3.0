from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from app.core.enums import PositionSide


UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Fill:
    """Immutable execution fact used by the fill ledger."""

    fill_id: str
    order_id: str
    symbol: str
    side: PositionSide
    quantity: Decimal
    price: Decimal
    commission: Decimal = Decimal("0")
    filled_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.fill_id or not self.order_id or not self.symbol:
            raise ValueError("fill_id, order_id, and symbol are required")
        if self.quantity <= 0:
            raise ValueError("Fill quantity must be positive")
        if self.price <= 0:
            raise ValueError("Fill price must be positive")
        if self.commission < 0:
            raise ValueError("Commission cannot be negative")
