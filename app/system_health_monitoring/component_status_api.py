"""Component status provider for health dashboard integration."""

from datetime import datetime, timezone
from typing import Any, Mapping


class ComponentStatusAPI:
    def get_status(self, components: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "components": dict(components),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
