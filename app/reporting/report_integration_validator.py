"""
Phase 31.4.3 - Report Integration & Validation

Validates the reporting pipeline output before export.
"""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]


class ReportIntegrationValidator:
    required_fields = {"report_type", "generated_at", "sections"}

    def validate(self, report: Dict[str, Any]) -> ValidationResult:
        errors = []
        missing = self.required_fields - set(report.keys())
        if missing:
            errors.extend([f"Missing field: {field}" for field in missing])

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
        )
