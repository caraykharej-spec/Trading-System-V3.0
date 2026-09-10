"""Runtime Status Monitor"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RuntimeStatus:
    state: str
    timestamp: datetime


class RuntimeStatusMonitor:
    def get_status(self) -> RuntimeStatus:
        return RuntimeStatus(
            state="RUNNING",
            timestamp=datetime.utcnow(),
        )
