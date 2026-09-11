"""Mobile health feed foundation for future Android integration."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass
class MobileHealthFeed:
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.utcnow)


class MobileHealthFeedProvider:
    def generate(
        self,
        status: str,
        data: Mapping[str, Any] | None = None,
    ) -> MobileHealthFeed:
        return MobileHealthFeed(
            status=status,
            data=dict(data or {}),
        )
