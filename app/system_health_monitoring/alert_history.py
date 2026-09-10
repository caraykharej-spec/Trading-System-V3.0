"""Alert history foundation."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class AlertHistory:
    alerts: List[object] = field(default_factory=list)

    def add(self, alert):
        self.alerts.append(alert)

    def get_all(self):
        return self.alerts
