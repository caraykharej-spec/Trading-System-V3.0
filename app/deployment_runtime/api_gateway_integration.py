"""
Phase 33.8.1 - API Gateway Integration

Foundation layer for routing Trading System services to external clients.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict


@dataclass
class APIRequest:
    route: str
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class APIRoute:
    name: str
    target: str
    enabled: bool = True


class APIGatewayIntegration:
    def __init__(self):
        self.routes: Dict[str, APIRoute] = {}

    def register_route(self, route: APIRoute):
        self.routes[route.name] = route

    def get_routes(self):
        return list(self.routes.values())

    def health(self):
        return {
            "status": "healthy",
            "routes": len(self.routes),
        }
