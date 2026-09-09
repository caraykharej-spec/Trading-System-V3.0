from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RiskPolicy:
    max_risk_per_trade_percent: Decimal = Decimal("1.0")
    max_aggregate_open_risk_percent: Decimal = Decimal("4.0")
    max_storm_sl_loss_percent_of_position_amount: Decimal = Decimal("10.0")
    max_futures_capital_percent: Decimal = Decimal("50.0")
    max_correlated_risk_percent: Decimal = Decimal("2.0")

    def validate(self) -> None:
        if not (Decimal("0") < self.max_risk_per_trade_percent <= Decimal("100")):
            raise ValueError("max_risk_per_trade_percent must be between 0 and 100")
        if not (Decimal("0") < self.max_aggregate_open_risk_percent <= Decimal("100")):
            raise ValueError("max_aggregate_open_risk_percent must be between 0 and 100")
        if not (Decimal("0") < self.max_storm_sl_loss_percent_of_position_amount <= Decimal("100")):
            raise ValueError("max_storm_sl_loss_percent_of_position_amount must be between 0 and 100")
        if not (Decimal("0") < self.max_futures_capital_percent <= Decimal("100")):
            raise ValueError("max_futures_capital_percent must be between 0 and 100")
        if not (Decimal("0") < self.max_correlated_risk_percent <= Decimal("100")):
            raise ValueError("max_correlated_risk_percent must be between 0 and 100")
