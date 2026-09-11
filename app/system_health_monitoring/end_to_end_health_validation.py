"""Phase 32.6 - End To End Health Validation foundation.

Provides a readiness gate before paper trading or live operation.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


@dataclass
class HealthValidationResult:
    passed: bool
    checks: dict[str, bool]
    checked_at: datetime


class EndToEndHealthValidator:
    def validate(self, checks: Mapping[str, bool]) -> HealthValidationResult:
        normalized = dict(checks)
        passed = all(normalized.values()) if normalized else False
        return HealthValidationResult(
            passed=passed,
            checks=normalized,
            checked_at=datetime.utcnow(),
        )
