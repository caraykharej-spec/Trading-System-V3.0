"""Runtime state definitions for Trading System lifecycle."""

from enum import Enum


class RuntimeState(str, Enum):
    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    SCANNING = "SCANNING"
    ANALYZING = "ANALYZING"
    RISK_CHECK = "RISK_CHECK"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"
