"""Bridge utilities between core orchestration and the composed application.

Keeps the core runtime independent while allowing the real V3 paper application
composition root to expose its services through the core container.
"""

from .container import TradingContainer


def build_core_container(application) -> TradingContainer:
    """Create a core container from a composed V3 application instance."""
    container = TradingContainer()

    container.register("portfolio_engine", application.account)
    container.register("position_repository", application.position_repository)
    container.register("opportunity_pipeline", application.opportunity_pipeline)
    container.register("runtime_engine", application.runtime)
    container.register("analytics_engine", application.analytics)
    container.register("health_service", application.health)
    container.register("api_service", application.api)

    return container
