from dataclasses import dataclass, field
from datetime import datetime


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
    def __init__(self) -> None:
        self.configs: dict[str, DatabaseConfig] = {}
        self.sessions: dict[str, DatabaseSession] = {}

    def register_database(self, config: DatabaseConfig) -> None:
        self.configs[config.name] = config

    def connect(self, name: str) -> None:
        if name in self.configs:
            self.configs[name].connected = True

    def health_check(self, name: str) -> dict[str, object]:
        config = self.configs.get(name)
        return {
            "database": name,
            "connected": bool(config and config.connected),
            "checked_at": datetime.utcnow().isoformat(),
        }
