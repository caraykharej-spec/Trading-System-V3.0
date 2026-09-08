from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

from .enums import PositionSide, PositionStatus
from .models import Position, PositionCloseResult, utc_now


LivePriceProvider = Callable[[str], Decimal]


@dataclass(frozen=True)
class MonitorSummary:
    monitored: int
    stopped_out: int
    results: tuple[PositionCloseResult, ...]


def stop_was_crossed(position: Position, live_price: Decimal) -> bool:
    """Return True when the live price has crossed the configured stop."""
    if position.side is PositionSide.LONG:
        return live_price <= position.stop_loss
    return live_price >= position.stop_loss


def calculate_realized_pnl(
    position: Position,
    exit_price: Decimal,
) -> Decimal:
    """Calculate P&L against the position amount.

    `total_amount` represents the position amount/collateral used by the
    contract model. Leverage is applied here because some providers, notably
    the current Storm contract model, express stop-loss P&L relative to that
    amount with leverage included. Provider-specific contract differences
    should be isolated in a provider adapter before this function is reused
    for non-linear instruments.
    """
    if position.entry_price <= 0 or position.total_amount < 0 or position.leverage <= 0:
        raise ValueError("Invalid position values for P&L calculation")

    price_return = (exit_price - position.entry_price) / position.entry_price
    if position.side is PositionSide.SHORT:
        price_return = -price_return

    return position.total_amount * price_return * position.leverage


def monitor_open_positions(
    positions: Iterable[Position],
    live_price_provider: LivePriceProvider,
) -> MonitorSummary:
    """Check every open position against live price and stop it if crossed."""
    results: list[PositionCloseResult] = []
    monitored = 0

    for position in positions:
        if position.status is not PositionStatus.OPEN:
            continue

        monitored += 1
        live_price = Decimal(str(live_price_provider(position.symbol)))
        if live_price <= 0:
            raise ValueError(f"Invalid live price for {position.symbol}: {live_price}")

        if not stop_was_crossed(position, live_price):
            continue

        pnl = calculate_realized_pnl(position, live_price)
        closed_at = utc_now()
        position.status = PositionStatus.STOPPED_OUT
        position.exit_price = live_price
        position.realized_pnl = pnl
        position.closed_at = closed_at
        position.close_reason = "STOP_LOSS"

        results.append(
            PositionCloseResult(
                position_id=position.position_id,
                exit_price=live_price,
                realized_pnl=pnl,
                reason="STOP_LOSS",
                closed_at=closed_at,
            )
        )

    return MonitorSummary(
        monitored=monitored,
        stopped_out=len(results),
        results=tuple(results),
    )
