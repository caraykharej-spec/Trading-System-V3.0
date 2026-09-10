from dataclasses import dataclass, field


@dataclass
class PortfolioState:
    cash_balance: float = 0.0
    equity: float = 0.0
    used_margin: float = 0.0
    available_balance: float = 0.0
    positions: dict = field(default_factory=dict)

    def update_equity(self, value: float):
        self.equity = value

    def snapshot(self):
        return {
            "cash_balance": self.cash_balance,
            "equity": self.equity,
            "used_margin": self.used_margin,
            "available_balance": self.available_balance,
            "positions": self.positions,
        }
