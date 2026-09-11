"""Mobile application export data contract."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass
class MobileDataFeed:
    status: str
    data: dict[str, Any]
    generated_at: datetime


class MobileFeedProvider:
    def generate(self, data: Mapping[str, Any]) -> MobileDataFeed:
        return MobileDataFeed(
            status="ready",
            data=dict(data),
            generated_at=datetime.utcnow(),
        )
