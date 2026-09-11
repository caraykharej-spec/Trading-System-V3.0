from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ReadinessCheck:
    name: str
    category: str
    passed: bool
    details: str = ""


@dataclass
class GoLiveReadinessReport:
    checks: list[ReadinessCheck] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def approved(self) -> bool:
        return all(check.passed for check in self.checks)


class GoLiveReadinessEngine:
    def __init__(self) -> None:
        self.checks: list[ReadinessCheck] = []

    def register_check(self, check: ReadinessCheck) -> None:
        self.checks.append(check)

    def generate_report(self) -> GoLiveReadinessReport:
        return GoLiveReadinessReport(checks=self.checks.copy())

    def health(self) -> dict[str, str]:
        return {
            "component": "go_live_readiness",
            "status": "healthy",
        }
