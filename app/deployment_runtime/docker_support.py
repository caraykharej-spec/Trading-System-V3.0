"""Docker support foundation for Trading System runtime."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ContainerConfig:
    name: str
    image: str
    enabled: bool = True


class DockerRuntimeManager:
    def __init__(self):
        self.containers = {}
        self.created_at = datetime.utcnow()

    def register_container(self, config: ContainerConfig):
        self.containers[config.name] = config

    def list_containers(self):
        return list(self.containers.values())

    def health(self):
        return {
            "status": "healthy",
            "containers": len(self.containers),
            "checked_at": datetime.utcnow().isoformat(),
        }
