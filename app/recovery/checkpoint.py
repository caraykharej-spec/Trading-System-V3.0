from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class RuntimeCheckpoint:
    cycle_id: str
    timestamp: datetime
    equity_snapshot: Decimal
    open_positions_hash: str
    pending_orders_hash: str
    journal_cursor: str | None = None
