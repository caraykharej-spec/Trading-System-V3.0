"""Export validation layer for Trading System.

Provides validation before exported artifacts are archived or consumed by
external clients such as dashboards and mobile applications.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ExportValidationResult:
    valid: bool
    errors: list[str]
    checked_at: datetime


class ExportValidator:
    def validate(self, export_payload: dict) -> ExportValidationResult:
        errors = []

        if not isinstance(export_payload, dict):
            errors.append("Export payload must be a dictionary")
        else:
            if "export_type" not in export_payload:
                errors.append("Missing export_type")
            if "data" not in export_payload:
                errors.append("Missing data")

        return ExportValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            checked_at=datetime.utcnow(),
        )
