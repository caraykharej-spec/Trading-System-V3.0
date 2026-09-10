"""Portfolio domain events."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class PortfolioUpdatedEvent:
    equity: float
    timestamp: datetime = datetime.utcnow()


@dataclass
class BalanceUpdatedEvent:
    balance: float
    timestamp: datetime = datetime.utcnow()
