from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .incident_management import IncidentManager
from .realtime_monitoring import LiveOperationMonitor


@dataclass(frozen=True)
class TradingOperationsSnapshot:
    live_status: str
    metric_count: int
    active_incidents: int
    critical_incident_open: bool
    captured_at: datetime


class TradingOperationsDashboard:
    """Read-only operational snapshot provider for UI/API consumers."""

    def __init__(
        self,
        monitor: LiveOperationMonitor,
        incidents: IncidentManager,
    ) -> None:
        self.monitor = monitor
        self.incidents = incidents

    def snapshot(self) -> TradingOperationsSnapshot:
        monitoring = self.monitor.snapshot()
        active = self.incidents.active()
        return TradingOperationsSnapshot(
            live_status=monitoring.status,
            metric_count=len(monitoring.metrics),
            active_incidents=len(active),
            critical_incident_open=self.incidents.has_critical_open_incident(),
            captured_at=datetime.now(timezone.utc),
        )
