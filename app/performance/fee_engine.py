"""Fee calculation engine for portfolio performance tracking."""

from dataclasses import dataclass


@dataclass
class FeeSnapshot:
    trading_fee: float = 0.0
    funding_fee: float = 0.0

    @property
    def total_fee(self) -> float:
        return self.trading_fee + self.funding_fee


class FeeEngine:
    def calculate(self, notional: float, fee_rate: float, funding_fee: float = 0.0) -> FeeSnapshot:
        return FeeSnapshot(
            trading_fee=notional * fee_rate,
            funding_fee=funding_fee,
        )
