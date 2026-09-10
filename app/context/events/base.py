from __future__ import annotations

from typing import Protocol

from app.context.models import EconomicEvent


class EventProvider(Protocol):
    """Contract for public/no-key economic-event sources."""

    name: str
    requires_credentials: bool

    def fetch(self, *, limit: int = 100) -> list[EconomicEvent]:
        ...
