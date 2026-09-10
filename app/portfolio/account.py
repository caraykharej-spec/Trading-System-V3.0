from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.models import Position
from app.risk.risk_math import aggregate_open_risk


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
        return aggregate_open_risk(positions)
