from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any


@dataclass
class DatabaseConfig:
    name: str
    engine: str = "sqlite"
    connected: bool = False


@dataclass
class DatabaseSession:
    session_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)


class DatabaseRuntime:
    def __init__(self):
        self.configs: Dict[str, DatabaseConfig] = {}
        self.sessions: Dict[str, DatabaseSession] = {}

    def register_database(self, config: DatabaseConfig):
        self.configs[config.name] = config

    def connect(self, name: str):
        if name in self.configs:
            self.configs[name].connected = True

    def health_check(self, name: str) -> Dict[str, Any]:
        config = self.configs.get(name)
        return {
            "database": name,
            "connected": bool(config and config.connected),
            "checked_at": datetime.utcnow().isoformat(),
        }
