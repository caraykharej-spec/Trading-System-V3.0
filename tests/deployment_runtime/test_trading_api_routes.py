from app.deployment_runtime.trading_api_routes import (
    TradingAPIRegistry,
    TradingAPIRoute,
)


def test_route_registration():
    registry = TradingAPIRegistry()
    registry.register(
        TradingAPIRoute(
            name="portfolio",
            target="Portfolio Engine",
        )
    )

    assert len(registry.list_routes()) == 1


def test_route_health():
    registry = TradingAPIRegistry()
    assert registry.health()["status"] == "healthy"
