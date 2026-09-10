"""
Phase 34.5 — Strategy Execution Validation

Validates strategy workflow readiness inside production operation layer.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class StrategyCheck:
    name: str
    component: str
    passed: bool = True
    details: str = ""


@dataclass
class StrategyValidationReport:
    checks: list[StrategyCheck] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


class StrategyExecutionValidationEngine:
    def __init__(self):
        self.checks: list[StrategyCheck] = []

    def register_check(self, check: StrategyCheck):
        self.checks.append(check)

    def validate(self) -> StrategyValidationReport:
        return StrategyValidationReport(checks=self.checks.copy())

    def health(self):
        return {
            "component": "strategy_execution_validation",
            "status": "healthy",
            "checks": len(self.checks),
        }
