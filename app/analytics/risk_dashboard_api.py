"""Risk Dashboard API integration layer.

Provides dashboard-ready risk snapshots and alert feeds.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class RiskDashboardSnapshot:
    risk_state: str
    equity: float
    exposure: float
    margin_ratio: float
    drawdown: float
    alerts: List[Dict[str, Any]] = field(default_factory=list)


class RiskDashboardAPI:
    def __init__(self, provider):
        self.provider = provider

    def get_snapshot(self) -> RiskDashboardSnapshot:
        return self.provider.get_risk_snapshot()

    def get_alert_feed(self):
        snapshot = self.get_snapshot()
        return snapshot.alerts
