from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol


UTC = timezone.utc


class AuditStatus(str, Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CycleAudit:
    cycle_id: str
    status: AuditStatus
    started_at: datetime
    finished_at: datetime | None = None
    monitored_positions: int = 0
    stopped_positions: int = 0
    filled_orders: int = 0
    notes: tuple[str, ...] = ()


class CycleAuditRepository(Protocol):
    def save(self, audit: CycleAudit) -> None: ...
    def get(self, cycle_id: str) -> CycleAudit | None: ...
    def latest(self) -> CycleAudit | None: ...


class InMemoryCycleAuditRepository:
    def __init__(self) -> None:
        self._items: dict[str, CycleAudit] = {}

    def save(self, audit: CycleAudit) -> None:
        self._items[audit.cycle_id] = audit

    def get(self, cycle_id: str) -> CycleAudit | None:
        return self._items.get(cycle_id)

    def latest(self) -> CycleAudit | None:
        if not self._items:
            return None
        return max(self._items.values(), key=lambda item: item.started_at)
