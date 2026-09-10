"""Notification interface foundation for system health alerts."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Notification:
    channel: str
    message: str
    status: str = "pending"
    created_at: datetime = datetime.utcnow()


class NotificationInterface:
    def send(self, notification: Notification) -> Notification:
        notification.status = "sent"
        return notification
