"""Portfolio domain events."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class PortfolioUpdatedEvent:
    portfolio_id: str
    equity: float
    timestamp: datetime


@dataclass
class BalanceUpdatedEvent:
    total_balance: float
    available_balance: float
    timestamp: datetime


@dataclass
class EquityChangedEvent:
    previous_equity: float
    current_equity: float
    timestamp: datetime
