from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class ReadinessCheck:
    name: str
    category: str
    passed: bool
    details: str = ""


@dataclass
class GoLiveReadinessReport:
    checks: List[ReadinessCheck] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def approved(self) -> bool:
        return all(check.passed for check in self.checks)


class GoLiveReadinessEngine:
    def __init__(self):
        self.checks: List[ReadinessCheck] = []

    def register_check(self, check: ReadinessCheck):
        self.checks.append(check)

    def generate_report(self) -> GoLiveReadinessReport:
        return GoLiveReadinessReport(checks=self.checks)

    def health(self):
        return {
            "component": "go_live_readiness",
            "status": "healthy"
        }
