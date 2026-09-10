"""Alert Engine foundation for System Health Monitoring."""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict


@dataclass
class Alert:
    alert_type: str
    severity: str
    message: str
    created_at: datetime


class AlertEngine:
    def create_alert(self, alert_type: str, severity: str, message: str) -> Alert:
        return Alert(
            alert_type=alert_type,
            severity=severity,
            message=message,
            created_at=datetime.utcnow(),
        )

    def evaluate_health(self, health_state: Dict[str, str]):
        alerts = []
        for component, status in health_state.items():
            if status != "healthy":
                alerts.append(
                    self.create_alert(
                        component,
                        "warning",
                        f"Component status is {status}",
                    )
                )
        return alerts
