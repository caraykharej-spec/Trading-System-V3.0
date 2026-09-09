from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.models import Position
from app.portfolio.account import Account


@dataclass(frozen=True)
class Exposure:
    symbol: str
    notional: Decimal
    risk: Decimal


def position_risk(position: Position) -> Decimal:
    if position.status.value != "OPEN":
        return Decimal("0")
    distance = abs(position.entry_price - position.stop_loss) / position.entry_price
    return position.total_amount * distance * position.leverage


def build_exposure(positions: list[Position]) -> list[Exposure]:
    return [Exposure(p.symbol, p.total_amount, position_risk(p)) for p in positions if p.status.value == "OPEN"]


def total_notional(positions: list[Position]) -> Decimal:
    return sum((p.total_amount for p in positions if p.status.value == "OPEN"), Decimal("0"))


def total_risk(positions: list[Position]) -> Decimal:
    return sum((position_risk(p) for p in positions), Decimal("0"))
