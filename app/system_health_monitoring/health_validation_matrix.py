"""Phase 32.6.1 Health Validation Matrix.

Provides structured production readiness checks for system components.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ValidationCheck:
    name: str
    passed: bool
    details: str = ""


@dataclass
class ValidationReport:
    checks: list[ValidationCheck] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.checks)


class HealthValidationMatrix:
    def __init__(self):
        self.checks = []

    def add_check(self, name: str, passed: bool, details: str = ""):
        self.checks.append(ValidationCheck(name, passed, details))

    def generate_report(self) -> ValidationReport:
        return ValidationReport(self.checks)
