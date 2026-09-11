"""Oracle health monitoring foundation."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class OracleHealthStatus:
    oracle: str
    healthy: bool
    data_fresh: bool
    checked_at: str = ""


class OracleHealthMonitor:
    def check(
        self,
        oracle: str,
        healthy: bool = True,
        data_fresh: bool = True,
    ) -> OracleHealthStatus:
        return OracleHealthStatus(
            oracle=oracle,
            healthy=healthy,
            data_fresh=data_fresh,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
