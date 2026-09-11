"""API Server Layer foundation.

Provides API contracts for dashboard, mobile and external integrations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class APIResponse:
    endpoint: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


class APIServerLayer:
    def __init__(self) -> None:
        self.routes: dict[str, str] = {}

    def register_route(self, path: str, handler: str) -> None:
        self.routes[path] = handler

    def health(self) -> APIResponse:
        return APIResponse(
            endpoint="/health",
            payload={"status": "ok"},
        )
