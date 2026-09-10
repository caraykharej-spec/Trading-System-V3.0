"""Domain event contracts for event-driven trading workflows."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    event_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketEvent(DomainEvent):
    event_type: str = "MARKET_UPDATE"


@dataclass(frozen=True)
class SignalEvent(DomainEvent):
    event_type: str = "SIGNAL_GENERATED"


@dataclass(frozen=True)
class RiskEvent(DomainEvent):
    event_type: str = "RISK_DECISION"


@dataclass(frozen=True)
class ExecutionEvent(DomainEvent):
    event_type: str = "EXECUTION_UPDATE"
