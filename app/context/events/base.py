from __future__ import annotations

from typing import Protocol

from app.context.models import EconomicEvent


class EventProvider(Protocol):
    name: str

    def fetch(self, *, limit: int = 100) -> list[EconomicEvent]:
        ...
