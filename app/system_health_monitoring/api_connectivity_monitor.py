"""API Connectivity Monitor foundation for Phase 32.1."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class APIHealthStatus:
    service: str
    available: bool
    latency_ms: float = 0.0
    checked_at: str = ""


class APIConnectivityMonitor:
    def check(self, service: str, latency_ms: float = 0.0, available: bool = True):
        return APIHealthStatus(
            service=service,
            available=available,
            latency_ms=latency_ms,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
