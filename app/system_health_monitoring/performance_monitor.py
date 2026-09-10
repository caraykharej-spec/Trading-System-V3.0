"""Performance monitoring foundation for system health layer."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class PerformanceMetric:
    metric: str
    value: float
    recorded_at: str


class PerformanceMonitor:
    def record(self, metric: str, value: float) -> PerformanceMetric:
        return PerformanceMetric(
            metric=metric,
            value=value,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )

    def execution_latency(self, milliseconds: float) -> PerformanceMetric:
        return self.record("execution_latency_ms", milliseconds)

    def cycle_duration(self, seconds: float) -> PerformanceMetric:
        return self.record("cycle_duration_seconds", seconds)
