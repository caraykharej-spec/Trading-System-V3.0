"""Domain events used for decoupled system communication."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TradingEvent:
    event_type: str
    created_at: datetime
    payload: dict
