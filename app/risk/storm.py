from __future__ import annotations

from decimal import Decimal


def storm_sl_loss_percent(*, entry: Decimal, stop_loss: Decimal, leverage: Decimal) -> Decimal:
    """Storm hard-contract estimate: price-distance percent multiplied by leverage."""
    if entry <= 0 or leverage <= 0:
        raise ValueError("entry and leverage must be positive")
    if stop_loss <= 0:
        raise ValueError("stop_loss must be positive")
    price_distance_percent = abs(entry - stop_loss) / entry * Decimal("100")
    return price_distance_percent * leverage
