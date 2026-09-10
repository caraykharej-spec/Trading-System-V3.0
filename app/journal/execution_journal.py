"""Execution journal integration.

Stores normalized execution records without coupling Journal to Execution Engine.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ExecutionRecord:
    request_id: str
    symbol: str
    status: str
    quantity: float
    price: float | None
    timestamp: str


class ExecutionJournal:
    def __init__(self):
        self.records = []

    def record(self, result: ExecutionRecord):
        self.records.append(result)

    def latest(self):
        return self.records[-1] if self.records else None
