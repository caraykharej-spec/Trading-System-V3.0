"""System Health Dashboard API foundation."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence


@dataclass
class HealthDashboardSnapshot:
    status: str
    components: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


class SystemHealthDashboardAPI:
    def create_snapshot(
        self,
        status: str,
        components: Mapping[str, Any] | None = None,
    ) -> HealthDashboardSnapshot:
        return HealthDashboardSnapshot(
            status=status,
            components=dict(components or {}),
        )

    def get_component_status(self, components: Mapping[str, Any]) -> dict[str, Any]:
        return dict(components)

    def get_alert_feed(self, alerts: Sequence[Any]) -> list[Any]:
        return list(alerts)
