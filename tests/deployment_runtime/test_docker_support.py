from app.deployment_runtime.docker_support import (
    ContainerConfig,
    DockerRuntimeManager,
)


def test_container_registration():
    manager = DockerRuntimeManager()
    manager.register_container(ContainerConfig(name="api", image="trading-api"))

    assert len(manager.list_containers()) == 1


def test_docker_health():
    manager = DockerRuntimeManager()
    result = manager.health()

    assert result["status"] == "healthy"
