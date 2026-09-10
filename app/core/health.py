"""Core health state helpers."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class CoreHealth:
    status: str
    timestamp: str


def healthy() -> CoreHealth:
    return CoreHealth(
        status="READY",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
