from app.deployment_runtime.docker_compose_layer import DockerComposeManager, ServiceContainer


def test_service_registration():
    manager = DockerComposeManager()
    manager.register_service(ServiceContainer(name="api", image="trading-api"))
    assert "api" in manager.list_services()


def test_compose_health():
    manager = DockerComposeManager()
    assert manager.health() is True
