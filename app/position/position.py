"""Position domain model for portfolio management."""

from dataclasses import dataclass
from enum import Enum
from datetime import datetime


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(str, Enum):
    NONE = "NONE"
    OPENING = "OPENING"
    OPEN = "OPEN"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    CLOSED = "CLOSED"


@dataclass
class Position:
    symbol: str
    side: PositionSide
    quantity: float
    entry_price: float
    average_price: float
    leverage: float = 1.0
    margin: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    created_at: datetime | None = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
