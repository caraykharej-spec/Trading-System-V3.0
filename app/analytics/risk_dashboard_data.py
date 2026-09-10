"""Risk dashboard data contract."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class RiskDashboardData:
    risk_state: str
    equity: float
    exposure: float
    margin_ratio: float
    drawdown: float
    alerts: List[str] = field(default_factory=list)

    def is_safe(self) -> bool:
        return self.risk_state == "NORMAL"
