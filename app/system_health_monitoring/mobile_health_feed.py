"""Mobile health feed foundation for future Android integration."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MobileHealthFeed:
    status: str
    data: dict = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.utcnow)


class MobileHealthFeedProvider:
    def generate(self, status: str, data: dict | None = None):
        return MobileHealthFeed(
            status=status,
            data=data or {},
        )
