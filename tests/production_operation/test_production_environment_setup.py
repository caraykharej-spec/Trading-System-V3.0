from app.production_operation.production_environment_setup import (
    ProductionEnvironment,
    ProductionEnvironmentManager,
)


def test_production_environment_registration():
    manager = ProductionEnvironmentManager()
    manager.register(
        ProductionEnvironment(
            name="production",
            mode="paper",
            services=["api", "worker", "database"],
        )
    )

    assert manager.validate("production") is True


def test_production_environment_health():
    manager = ProductionEnvironmentManager()
    assert manager.health()["status"] == "healthy"
