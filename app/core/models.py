from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from .enums import CycleStatus, PositionSide, PositionStatus


UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Position:
    position_id: str
    symbol: str
    side: PositionSide
    entry_price: Decimal
    stop_loss: Decimal
    total_amount: Decimal
    quantity: Decimal
    leverage: Decimal = Decimal("1")
    status: PositionStatus = PositionStatus.OPEN
    opened_at: datetime = field(default_factory=utc_now)
    closed_at: Optional[datetime] = None
    exit_price: Optional[Decimal] = None
    realized_pnl: Optional[Decimal] = None
    close_reason: Optional[str] = None


@dataclass(frozen=True)
class PositionCloseResult:
    position_id: str
    exit_price: Decimal
    realized_pnl: Decimal
    reason: str
    closed_at: datetime


@dataclass(frozen=True)
class CycleResult:
    cycle_id: str
    status: CycleStatus
    started_at: datetime
    finished_at: datetime
    monitored_positions: int
    stopped_positions: int
    notes: tuple[str, ...] = ()
