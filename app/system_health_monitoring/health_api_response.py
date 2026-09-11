"""Standard response models for health dashboard APIs."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class HealthAPIResponse:
    endpoint: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def is_valid(self) -> bool:
        return bool(self.endpoint and isinstance(self.payload, dict))
