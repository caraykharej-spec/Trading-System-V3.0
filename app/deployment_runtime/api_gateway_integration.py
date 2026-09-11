"""
Phase 33.8.1 - API Gateway Integration

Foundation layer for routing Trading System services to external clients.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class APIRequest:
    route: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class APIRoute:
    name: str
    target: str
    enabled: bool = True


class APIGatewayIntegration:
    def __init__(self) -> None:
        self.routes: dict[str, APIRoute] = {}

    def register_route(self, route: APIRoute) -> None:
        self.routes[route.name] = route

    def get_routes(self) -> list[APIRoute]:
        return list(self.routes.values())

    def health(self) -> dict[str, object]:
        return {
            "status": "healthy",
            "routes": len(self.routes),
        }
