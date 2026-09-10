"""Error tracking foundation for system health monitoring."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class ErrorRecord:
    error_type: str
    message: str
    severity: str
    created_at: str


class ErrorTracker:
    def capture(self, error_type: str, message: str, severity: str = "medium") -> ErrorRecord:
        return ErrorRecord(
            error_type=error_type,
            message=message,
            severity=severity,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def classify(self, error: Exception) -> ErrorRecord:
        return self.capture(type(error).__name__, str(error))
