"""API Server Layer foundation.

Provides API contracts for dashboard, mobile and external integrations.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict


@dataclass
class APIResponse:
    endpoint: str
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


class APIServerLayer:
    def __init__(self):
        self.routes = {}

    def register_route(self, path: str, handler: str):
        self.routes[path] = handler

    def health(self) -> APIResponse:
        return APIResponse(
            endpoint="/health",
            payload={"status": "ok"},
        )
