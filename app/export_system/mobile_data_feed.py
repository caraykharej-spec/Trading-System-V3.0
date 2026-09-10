"""Mobile application export data contract."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MobileDataFeed:
    status: str
    data: dict
    generated_at: datetime


class MobileFeedProvider:
    def generate(self, data: dict) -> MobileDataFeed:
        return MobileDataFeed(
            status="ready",
            data=data,
            generated_at=datetime.utcnow(),
        )
