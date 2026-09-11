"""Service configuration layer for runtime deployment infrastructure."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ServiceConfiguration:
    name: str
    enabled: bool = True
    settings: dict[str, object] = field(default_factory=dict)


class ServiceRegistry:
    def __init__(self) -> None:
        self.services: dict[str, ServiceConfiguration] = {}

    def register(self, service: ServiceConfiguration) -> None:
        self.services[service.name] = service

    def get(self, name: str) -> ServiceConfiguration | None:
        return self.services.get(name)


class RuntimeConfigLoader:
    def __init__(self, environment: str = "development") -> None:
        self.environment = environment
        self.loaded_at = datetime.utcnow()

    def load(self) -> dict[str, str]:
        return {
            "environment": self.environment,
            "loaded_at": self.loaded_at.isoformat(),
        }
