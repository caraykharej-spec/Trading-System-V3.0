"""Phase 33.6 - Logging Infrastructure Core

Provides structured logging foundation for runtime services.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class LogRecord:
    level: str
    message: str
    component: str
    created_at: datetime = field(default_factory=datetime.utcnow)


class StructuredLogger:
    def __init__(self):
        self.records: List[LogRecord] = []

    def log(self, level: str, message: str, component: str):
        record = LogRecord(level=level, message=message, component=component)
        self.records.append(record)
        return record

    def info(self, message: str, component: str):
        return self.log("INFO", message, component)

    def error(self, message: str, component: str):
        return self.log("ERROR", message, component)

    def get_logs(self) -> List[Dict]:
        return [
            {
                "level": item.level,
                "message": item.message,
                "component": item.component,
                "created_at": item.created_at.isoformat(),
            }
            for item in self.records
        ]
