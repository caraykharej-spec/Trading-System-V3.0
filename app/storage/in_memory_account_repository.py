from __future__ import annotations

from decimal import Decimal

from .account_repository import AccountRepository


class InMemoryAccountRepository(AccountRepository):
    def __init__(self, equity: Decimal) -> None:
        if equity < 0:
            raise ValueError("equity cannot be negative")
        self._equity = equity

    def load_equity(self) -> Decimal:
        return self._equity

    def save_equity(self, equity: Decimal) -> None:
        if equity < 0:
            raise ValueError("equity cannot be negative")
        self._equity = equity
