"""Health Monitor Core
Central coordinator for system health checks.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict


@dataclass
class HealthStatus:
    status: str
    checks: Dict[str, str] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.utcnow)


class HealthMonitorCore:
    def run_check(self) -> HealthStatus:
        return HealthStatus(
            status="HEALTHY",
            checks={
                "runtime": "UNKNOWN",
                "data_pipeline": "UNKNOWN",
                "api": "UNKNOWN",
            },
        )
