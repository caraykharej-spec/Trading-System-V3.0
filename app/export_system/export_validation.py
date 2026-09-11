"""Export validation layer for Trading System.

Provides validation before exported artifacts are archived or consumed by
external clients such as dashboards and mobile applications.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ExportValidationResult:
    valid: bool
    errors: list[str]
    checked_at: datetime


class ExportValidator:
    def validate(self, export_payload: dict[str, Any]) -> ExportValidationResult:
        errors: list[str] = []

        if "export_type" not in export_payload:
            errors.append("Missing export_type")
        if "data" not in export_payload:
            errors.append("Missing data")

        return ExportValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            checked_at=datetime.utcnow(),
        )
