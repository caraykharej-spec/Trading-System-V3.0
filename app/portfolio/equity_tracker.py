"""Equity calculation layer."""

from dataclasses import dataclass


@dataclass
class EquityTracker:
    balance: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def equity(self) -> float:
        return self.balance + self.unrealized_pnl

    def update_unrealized_pnl(self, pnl: float) -> None:
        self.unrealized_pnl = pnl
