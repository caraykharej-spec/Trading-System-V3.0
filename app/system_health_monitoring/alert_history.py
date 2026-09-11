"""Alert history foundation."""

from dataclasses import dataclass, field


@dataclass
class AlertHistory:
    alerts: list[object] = field(default_factory=list)

    def add(self, alert: object) -> None:
        self.alerts.append(alert)

    def get_all(self) -> list[object]:
        return list(self.alerts)
