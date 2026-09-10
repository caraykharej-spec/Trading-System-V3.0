"""Execution domain models.

These models keep Strategy, Risk and exchange adapters decoupled.
"""

from dataclasses import dataclass
from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionStatus(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


@dataclass
class ExecutionRequest:
    symbol: str
    side: OrderSide
    quantity: float
    price: float | None = None
    reduce_only: bool = False


@dataclass
class ExecutionResult:
    request_id: str
    status: ExecutionStatus
    message: str = ""
