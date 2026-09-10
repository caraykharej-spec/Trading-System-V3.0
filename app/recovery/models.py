from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RecoveryState(str, Enum):
    STARTING = "STARTING"
    LOADING_STATE = "LOADING_STATE"
    VALIDATING = "VALIDATING"
    RECONCILING = "RECONCILING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"


@dataclass(frozen=True)
class RecoveryReport:
    state: RecoveryState
    positions_checked: int = 0
    positions_recovered: int = 0
    ledger_repairs: int = 0
    journal_events_checked: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)
