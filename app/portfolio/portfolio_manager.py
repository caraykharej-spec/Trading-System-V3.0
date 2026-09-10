"""Portfolio management core layer.

Coordinates portfolio state updates from position and execution flows.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class PortfolioManager:
    state: object
    positions: Dict[str, object] = field(default_factory=dict)

    def update_position(self, symbol: str, position: object) -> None:
        self.positions[symbol] = position

    def snapshot(self):
        return {
            "equity": self.state.equity,
            "balance": self.state.balance,
            "positions": self.positions,
        }
