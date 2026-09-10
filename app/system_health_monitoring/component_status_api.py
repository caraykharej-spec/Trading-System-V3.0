"""Component status provider for health dashboard integration."""

from datetime import datetime, timezone


class ComponentStatusAPI:
    def get_status(self, components: dict) -> dict:
        return {
            "components": components,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
