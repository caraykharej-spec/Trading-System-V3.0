"""Position synchronization boundary.

Keeps execution results separated from portfolio state management.
"""

from dataclasses import dataclass


@dataclass
class PositionUpdate:
    symbol: str
    quantity: float
    average_price: float


class PositionSynchronizer:
    def apply_execution(self, execution_result):
        if execution_result.status.value != "FILLED":
            return None

        return PositionUpdate(
            symbol=getattr(execution_result, "symbol", ""),
            quantity=getattr(execution_result, "quantity", 0.0),
            average_price=getattr(execution_result, "price", 0.0),
        )
