"""Balance tracking component."""

from dataclasses import dataclass


@dataclass
class BalanceManager:
    balance: float = 0.0
    locked_margin: float = 0.0

    @property
    def available_balance(self) -> float:
        return self.balance - self.locked_margin

    def deposit(self, amount: float) -> None:
        self.balance += amount

    def reserve_margin(self, amount: float) -> None:
        self.locked_margin += amount
