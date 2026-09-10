"""Storm Trade execution adapter boundary.

This module intentionally contains no live trading connection.
It defines the future integration contract only.
"""

from abc import ABC, abstractmethod


class StormExecutionAdapter(ABC):
    """Interface for future Storm Trade integration."""

    @abstractmethod
    def submit_order(self, order_request):
        raise NotImplementedError

    @abstractmethod
    def get_position_state(self, symbol: str):
        raise NotImplementedError


class PaperStormAdapter(StormExecutionAdapter):
    """Placeholder adapter for development and testing."""

    def submit_order(self, order_request):
        return {"status": "accepted", "mode": "paper"}

    def get_position_state(self, symbol: str):
        return {"symbol": symbol, "mode": "paper"}
