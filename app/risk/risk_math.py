from __future__ import annotations

from decimal import Decimal

from app.core.models import Position


HUNDRED = Decimal("100")


def candidate_risk_amount(
    *, total_amount: Decimal, entry: Decimal, stop_loss: Decimal, leverage: Decimal
) -> Decimal:
    if total_amount < 0 or entry <= 0 or stop_loss <= 0 or leverage <= 0:
        raise ValueError("risk inputs must be positive and amount non-negative")
    return total_amount * abs(entry - stop_loss) / entry * leverage


def position_open_risk(position: Position) -> Decimal:
    if position.status.value != "OPEN":
        return Decimal("0")
    return candidate_risk_amount(
        total_amount=position.total_amount,
        entry=position.entry_price,
        stop_loss=position.stop_loss,
        leverage=position.leverage,
    )


def aggregate_open_risk(positions: list[Position]) -> Decimal:
    return sum((position_open_risk(position) for position in positions), Decimal("0"))


def risk_budget_amount(equity: Decimal, percent: Decimal) -> Decimal:
    if equity <= 0:
        raise ValueError("equity must be positive")
    if percent < 0 or percent > HUNDRED:
        raise ValueError("risk percent must be between 0 and 100")
    return equity * percent / HUNDRED


def available_aggregate_risk(
    *, equity: Decimal, max_aggregate_percent: Decimal, committed_risk: Decimal
) -> Decimal:
    if committed_risk < 0:
        raise ValueError("committed_risk cannot be negative")
    return max(
        Decimal("0"),
        risk_budget_amount(equity, max_aggregate_percent) - committed_risk,
    )
