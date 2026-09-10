from app.deployment_runtime.service_configuration import (
    ServiceConfiguration,
    ServiceRegistry,
    RuntimeConfigLoader,
)


def test_service_registry_registration():
    registry = ServiceRegistry()
    registry.register(ServiceConfiguration(name="execution_engine"))
    assert registry.get("execution_engine") is not None


def test_runtime_config_loader():
    config = RuntimeConfigLoader("paper").load()
    assert config["environment"] == "paper"
