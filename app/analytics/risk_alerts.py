"""Risk Alerts Pipeline foundation for Analytics Layer."""

from dataclasses import dataclass
from enum import Enum


class RiskAlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"


@dataclass
class RiskAlert:
    alert_type: str
    level: RiskAlertLevel
    message: str


class RiskAlertEngine:
    def evaluate(self, drawdown: float, margin_ratio: float, exposure_ratio: float):
        alerts = []

        if drawdown >= 0.20:
            alerts.append(RiskAlert("DRAWDOWN", RiskAlertLevel.HIGH, "Maximum drawdown threshold exceeded"))
        elif drawdown >= 0.10:
            alerts.append(RiskAlert("DRAWDOWN", RiskAlertLevel.WARNING, "Drawdown warning"))

        if margin_ratio >= 0.80:
            alerts.append(RiskAlert("MARGIN", RiskAlertLevel.HIGH, "High margin usage"))
        elif margin_ratio >= 0.50:
            alerts.append(RiskAlert("MARGIN", RiskAlertLevel.WARNING, "Margin usage warning"))

        if exposure_ratio >= 0.90:
            alerts.append(RiskAlert("EXPOSURE", RiskAlertLevel.HIGH, "High portfolio exposure"))

        return alerts
