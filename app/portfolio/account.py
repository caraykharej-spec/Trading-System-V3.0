from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.models import Position


@dataclass
class Account:
    """Portfolio-level accounting state used by risk and ranking."""

    starting_equity: Decimal
    realized_pnl: Decimal = Decimal("0")

    @property
    def equity(self) -> Decimal:
        return self.starting_equity + self.realized_pnl

    def apply_realized_pnl(self, pnl: Decimal) -> None:
        self.realized_pnl += pnl

    def aggregate_open_risk(self, positions: list[Position]) -> Decimal:
        """Return absolute open risk in account currency from position SLs."""
        total = Decimal("0")
        for position in positions:
            if position.status.value != "OPEN":
                continue
            if position.entry_price <= 0 or position.total_amount < 0 or position.leverage <= 0:
                raise ValueError(f"Invalid open position: {position.position_id}")
            distance = abs(position.stop_loss - position.entry_price) / position.entry_price
            total += position.total_amount * distance * position.leverage
        return total
