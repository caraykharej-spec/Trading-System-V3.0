"""Recovery state tracking foundation."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RecoveryStatus:
    component: str
    state: str
    updated_at: datetime = field(default_factory=datetime.utcnow)


class RecoveryTracker:
    def __init__(self) -> None:
        self.history: list[RecoveryStatus] = []

    def record(self, recovery: RecoveryStatus) -> RecoveryStatus:
        self.history.append(recovery)
        return recovery

    def get_history(self) -> list[RecoveryStatus]:
        return self.history.copy()
