"""Execution slippage accounting model."""

from dataclasses import dataclass


@dataclass
class SlippageSnapshot:
    expected_price: float
    execution_price: float

    @property
    def cost(self) -> float:
        return abs(self.execution_price - self.expected_price)


class SlippageModel:
    def calculate(self, expected_price: float, execution_price: float) -> SlippageSnapshot:
        return SlippageSnapshot(
            expected_price=expected_price,
            execution_price=execution_price,
        )
