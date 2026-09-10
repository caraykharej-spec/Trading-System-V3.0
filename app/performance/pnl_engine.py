"""PnL calculation engine foundation."""

from dataclasses import dataclass


@dataclass
class PnLSnapshot:
    realized: float = 0.0
    unrealized: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0

    @property
    def net_pnl(self) -> float:
        return self.realized + self.unrealized - self.fees - self.slippage


class PNLEngine:
    def calculate_unrealized(self, entry_price: float, current_price: float, quantity: float, side: str) -> float:
        direction = 1 if side.upper() == "LONG" else -1
        return (current_price - entry_price) * quantity * direction

    def calculate_realized(self, entry_price: float, exit_price: float, quantity: float, side: str) -> float:
        direction = 1 if side.upper() == "LONG" else -1
        return (exit_price - entry_price) * quantity * direction
