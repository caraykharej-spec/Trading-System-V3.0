from dataclasses import dataclass
from typing import List


@dataclass
class RiskAnalyticsSnapshot:
    equity: float
    exposure: float
    drawdown: float
    margin_usage: float
    risk_state: str
    alerts: List[str]


class RiskAnalyticsView:
    def generate_snapshot(
        self,
        equity: float,
        exposure: float,
        drawdown: float,
        margin_usage: float,
    ) -> RiskAnalyticsSnapshot:
        alerts = []
        state = "NORMAL"

        if drawdown > 0.2:
            state = "HIGH_RISK"
            alerts.append("Drawdown threshold exceeded")

        if margin_usage > 0.8:
            state = "MARGIN_WARNING"
            alerts.append("High margin utilization")

        return RiskAnalyticsSnapshot(
            equity=equity,
            exposure=exposure,
            drawdown=drawdown,
            margin_usage=margin_usage,
            risk_state=state,
            alerts=alerts,
        )
