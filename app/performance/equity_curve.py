"""Equity curve tracking foundation."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EquityPoint:
    timestamp: datetime
    equity: float


@dataclass
class EquityCurve:
    points: list[EquityPoint] = field(default_factory=list)

    def add_point(self, timestamp: datetime, equity: float) -> None:
        self.points.append(EquityPoint(timestamp, equity))
