"""Service configuration layer for runtime deployment infrastructure."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict


@dataclass
class ServiceConfiguration:
    name: str
    enabled: bool = True
    settings: Dict[str, object] = field(default_factory=dict)


class ServiceRegistry:
    def __init__(self):
        self.services: Dict[str, ServiceConfiguration] = {}

    def register(self, service: ServiceConfiguration):
        self.services[service.name] = service

    def get(self, name: str):
        return self.services.get(name)


class RuntimeConfigLoader:
    def __init__(self, environment="development"):
        self.environment = environment
        self.loaded_at = datetime.utcnow()

    def load(self):
        return {
            "environment": self.environment,
            "loaded_at": self.loaded_at.isoformat(),
        }
