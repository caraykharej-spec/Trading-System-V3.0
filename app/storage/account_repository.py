from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal


class AccountRepository(ABC):
    """Persistence contract for account cash/equity state."""

    @abstractmethod
    def load_equity(self) -> Decimal:
        raise NotImplementedError

    @abstractmethod
    def save_equity(self, equity: Decimal) -> None:
        raise NotImplementedError
