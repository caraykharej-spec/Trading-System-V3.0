"""Docker support foundation for Trading System runtime."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ContainerConfig:
    name: str
    image: str
    enabled: bool = True


class DockerRuntimeManager:
    def __init__(self) -> None:
        self.containers: dict[str, ContainerConfig] = {}
        self.created_at = datetime.utcnow()

    def register_container(self, config: ContainerConfig) -> None:
        self.containers[config.name] = config

    def list_containers(self) -> list[ContainerConfig]:
        return list(self.containers.values())

    def health(self) -> dict[str, object]:
        return {
            "status": "healthy",
            "containers": len(self.containers),
            "checked_at": datetime.utcnow().isoformat(),
        }
