from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class LiveMetric:
    name: str
    value: float
    unit: str
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class LiveMonitoringSnapshot:
    status: str
    metrics: tuple[LiveMetric, ...]
    captured_at: datetime


class LiveOperationMonitor:
    """In-memory production telemetry collector for the Phase 35 runtime boundary."""

    def __init__(self) -> None:
        self._metrics: list[LiveMetric] = []
        self._status = "IDLE"

    def set_status(self, status: str) -> None:
        self._status = status.upper()

    def record(self, name: str, value: float, unit: str) -> LiveMetric:
        metric = LiveMetric(name=name, value=value, unit=unit)
        self._metrics.append(metric)
        return metric

    def snapshot(self) -> LiveMonitoringSnapshot:
        return LiveMonitoringSnapshot(
            status=self._status,
            metrics=tuple(self._metrics),
            captured_at=datetime.now(timezone.utc),
        )
