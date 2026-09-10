"""Portfolio state tracking primitives.

Keeps execution results separated from portfolio accounting.
"""

from dataclasses import dataclass, field


@dataclass
class PortfolioState:
    cash_balance: float = 0.0
    equity: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    positions: dict = field(default_factory=dict)

    def update_position(self, symbol: str, quantity: float):
        self.positions[symbol] = quantity
