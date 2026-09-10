"""System Health Dashboard API foundation."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class HealthDashboardSnapshot:
    status: str
    components: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


class SystemHealthDashboardAPI:
    def create_snapshot(self, status: str, components: dict | None = None):
        return HealthDashboardSnapshot(
            status=status,
            components=components or {},
        )

    def get_component_status(self, components: dict):
        return components

    def get_alert_feed(self, alerts: list):
        return alerts
