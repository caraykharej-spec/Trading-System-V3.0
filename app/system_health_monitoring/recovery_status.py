"""Recovery state tracking foundation."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RecoveryStatus:
    component: str
    state: str
    updated_at: datetime = datetime.utcnow()


class RecoveryTracker:
    def __init__(self):
        self.history = []

    def record(self, recovery: RecoveryStatus):
        self.history.append(recovery)
        return recovery

    def get_history(self):
        return self.history
