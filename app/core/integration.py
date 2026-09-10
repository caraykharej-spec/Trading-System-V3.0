"""Integration bridge between core runtime and application services."""

from __future__ import annotations

from typing import Any

from .container import TradingContainer


class CoreIntegration:
    """Registers production application components into the runtime container."""

    def __init__(self, container: TradingContainer):
        self.container = container

    def register_application(self, application: Any) -> TradingContainer:
        self.container.register("portfolio_engine", application.account)
        self.container.register("risk_engine", application.opportunity_pipeline)
        self.container.register("journal_engine", application.analytics)
        self.container.register("data_engine", application.live_router)
        self.container.register("runtime_engine", application.runtime)
        return self.container
