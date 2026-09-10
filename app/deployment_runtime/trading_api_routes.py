"""Trading System API Routes Foundation.

Provides route contracts for market, strategy, execution,
portfolio and risk services.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TradingAPIRoute:
    name: str
    target: str
    enabled: bool = True


@dataclass
class TradingAPIRegistry:
    routes: list[TradingAPIRoute] = field(default_factory=list)

    def register(self, route: TradingAPIRoute):
        self.routes.append(route)

    def list_routes(self):
        return self.routes

    def health(self):
        return {
            "status": "healthy",
            "routes": len(self.routes),
            "checked_at": datetime.utcnow().isoformat(),
        }


DEFAULT_ROUTES = [
    "market_data",
    "ranking",
    "strategy",
    "signal",
    "execution",
    "position",
    "portfolio",
    "risk",
    "analytics",
]
