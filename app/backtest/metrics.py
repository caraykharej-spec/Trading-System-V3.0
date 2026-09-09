from __future__ import annotations

from decimal import Decimal

from .models import TradeRecord


def calculate_metrics(initial_equity: Decimal, final_equity: Decimal, trades: tuple[TradeRecord, ...], equity_curve: list[Decimal]) -> tuple[Decimal, Decimal, Decimal | None, Decimal]:
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    wins = [t.realized_pnl for t in trades if t.realized_pnl > 0]
    losses = [-t.realized_pnl for t in trades if t.realized_pnl < 0]
    win_rate = (Decimal(len(wins)) / Decimal(len(trades)) * Decimal("100")) if trades else Decimal("0")
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = sum(losses, Decimal("0"))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (None if gross_profit == 0 else Decimal("Infinity"))

    peak = initial_equity
    max_drawdown = Decimal("0")
    for equity in equity_curve:
        if equity > peak:
            peak = equity
        if peak > 0:
            drawdown = (peak - equity) / peak * Decimal("100")
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    total_return = (final_equity - initial_equity) / initial_equity * Decimal("100")
    return win_rate, profit_factor, max_drawdown, total_return
