from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

from app.core.enums import PositionSide, PositionStatus
from app.core.models import Position, PositionCloseResult, utc_now


LivePriceProvider = Callable[[str], Decimal]


@dataclass(frozen=True)
class ExitPolicy:
    """Deterministic exit rules applied to an open position."""

    trailing_enabled: bool = False
    trailing_distance_percent: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.trailing_distance_percent < 0 or self.trailing_distance_percent >= 100:
            raise ValueError("trailing_distance_percent must be in [0, 100)")
        if self.trailing_enabled and self.trailing_distance_percent <= 0:
            raise ValueError("enabled trailing stop requires a positive distance")


@dataclass(frozen=True)
class PositionManagementResult:
    monitored: int
    closed: int
    stop_loss_exits: int
    take_profit_exits: int
    trailing_updates: int
    results: tuple[PositionCloseResult, ...]


def calculate_realized_pnl(position: Position, exit_price: Decimal) -> Decimal:
    """Calculate linear-contract P&L relative to total position amount."""
    if position.entry_price <= 0 or position.total_amount < 0 or position.leverage <= 0:
        raise ValueError("Invalid position values for P&L calculation")
    price_return = (exit_price - position.entry_price) / position.entry_price
    if position.side is PositionSide.SHORT:
        price_return = -price_return
    return position.total_amount * price_return * position.leverage


def _take_profit_crossed(position: Position, price: Decimal) -> bool:
    if position.take_profit is None:
        return False
    if position.side is PositionSide.LONG:
        return price >= position.take_profit
    return price <= position.take_profit


def _stop_crossed(position: Position, price: Decimal) -> bool:
    if position.side is PositionSide.LONG:
        return price <= position.stop_loss
    return price >= position.stop_loss


def _update_trailing_stop(position: Position, price: Decimal, policy: ExitPolicy) -> bool:
    if not policy.trailing_enabled:
        return False
    distance = policy.trailing_distance_percent / Decimal("100")
    if position.side is PositionSide.LONG:
        candidate = price * (Decimal("1") - distance)
        if candidate > position.stop_loss and candidate < price:
            position.stop_loss = candidate
            return True
    else:
        candidate = price * (Decimal("1") + distance)
        if candidate < position.stop_loss and candidate > price:
            position.stop_loss = candidate
            return True
    return False


def _close(position: Position, price: Decimal, reason: str) -> PositionCloseResult:
    pnl = calculate_realized_pnl(position, price)
    closed_at = utc_now()
    position.status = PositionStatus.CLOSED if reason == "TAKE_PROFIT" else PositionStatus.STOPPED_OUT
    position.exit_price = price
    position.realized_pnl = pnl
    position.closed_at = closed_at
    position.close_reason = reason
    return PositionCloseResult(
        position_id=position.position_id,
        exit_price=price,
        realized_pnl=pnl,
        reason=reason,
        closed_at=closed_at,
    )


def manage_open_positions(
    positions: Iterable[Position],
    live_price_provider: LivePriceProvider,
    policy: ExitPolicy | None = None,
) -> PositionManagementResult:
    """Monitor every open position, update trailing stops, and execute exits."""
    policy = policy or ExitPolicy()
    results: list[PositionCloseResult] = []
    monitored = closed = stop_loss_exits = take_profit_exits = trailing_updates = 0

    for position in positions:
        if position.status is not PositionStatus.OPEN:
            continue
        monitored += 1
        price = Decimal(str(live_price_provider(position.symbol)))
        if price <= 0:
            raise ValueError(f"Invalid live price for {position.symbol}: {price}")

        # Safety first: never move a stop before checking the current stop.
        if _stop_crossed(position, price):
            results.append(_close(position, price, "STOP_LOSS"))
            closed += 1
            stop_loss_exits += 1
            continue

        if _take_profit_crossed(position, price):
            results.append(_close(position, price, "TAKE_PROFIT"))
            closed += 1
            take_profit_exits += 1
            continue

        if _update_trailing_stop(position, price, policy):
            trailing_updates += 1
            # A newly raised/lowered trailing stop is not retroactively filled
            # at the same tick; the next live-price check handles the exit.

    return PositionManagementResult(
        monitored=monitored,
        closed=closed,
        stop_loss_exits=stop_loss_exits,
        take_profit_exits=take_profit_exits,
        trailing_updates=trailing_updates,
        results=tuple(results),
    )
