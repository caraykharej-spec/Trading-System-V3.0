"""Execution domain events.

Events emitted by execution layer and consumed by portfolio,
journal and monitoring components.
"""

from dataclasses import dataclass
from enum import Enum


class ExecutionEventType(str, Enum):
    SUBMITTED = "EXECUTION_SUBMITTED"
    FILLED = "EXECUTION_FILLED"
    REJECTED = "EXECUTION_REJECTED"


@dataclass
class ExecutionEvent:
    event_type: ExecutionEventType
    symbol: str
    request_id: str
    message: str = ""
