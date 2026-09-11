from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class IncidentSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class IncidentState(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


@dataclass
class TradingIncident:
    incident_id: str
    component: str
    message: str
    severity: IncidentSeverity
    state: IncidentState = IncidentState.OPEN
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IncidentManager:
    """Tracks operational incidents without embedding notification transport."""

    def __init__(self) -> None:
        self._incidents: dict[str, TradingIncident] = {}

    def open(self, incident: TradingIncident) -> None:
        if incident.incident_id in self._incidents:
            raise ValueError(f"duplicate incident id: {incident.incident_id}")
        self._incidents[incident.incident_id] = incident

    def acknowledge(self, incident_id: str) -> TradingIncident:
        incident = self._incidents[incident_id]
        incident.state = IncidentState.ACKNOWLEDGED
        incident.updated_at = datetime.now(timezone.utc)
        return incident

    def resolve(self, incident_id: str) -> TradingIncident:
        incident = self._incidents[incident_id]
        incident.state = IncidentState.RESOLVED
        incident.updated_at = datetime.now(timezone.utc)
        return incident

    def active(self) -> tuple[TradingIncident, ...]:
        return tuple(
            incident
            for incident in self._incidents.values()
            if incident.state != IncidentState.RESOLVED
        )

    def has_critical_open_incident(self) -> bool:
        return any(
            incident.severity == IncidentSeverity.CRITICAL
            and incident.state != IncidentState.RESOLVED
            for incident in self._incidents.values()
        )
