"""Environment configuration foundation for Phase 33."""

import os


class EnvironmentManager:
    def get(self, key: str, default=None):
        return os.getenv(key, default)

    def is_production(self) -> bool:
        return self.get("ENVIRONMENT", "development") == "production"
