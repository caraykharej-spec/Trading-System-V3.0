from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

from app.core.enums import PositionSide


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class OrderRequest:
    order_id: str
    symbol: str
    side: PositionSide
    order_type: OrderType
    quantity: Decimal
    requested_price: Optional[Decimal]
    stop_loss: Decimal
    take_profit: Optional[Decimal]
    leverage: Decimal = Decimal("1")
    created_at: datetime = field(default_factory=utc_now)
    decision_snapshot: Optional[str] = None


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    status: OrderStatus
    symbol: str
    filled_price: Optional[Decimal] = None
    reason: Optional[str] = None
    filled_at: Optional[datetime] = None
