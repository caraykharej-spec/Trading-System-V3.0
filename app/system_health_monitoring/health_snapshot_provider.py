"""Health snapshot provider for System Health Dashboard API."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class HealthSnapshot:
    status: str
    components: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HealthSnapshotProvider:
    def create_snapshot(self, components: dict[str, Any]) -> HealthSnapshot:
        status = "healthy" if all(components.values()) else "degraded"
        return HealthSnapshot(status=status, components=components)
