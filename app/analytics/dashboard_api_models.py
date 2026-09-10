from dataclasses import dataclass
from decimal import Decimal


@dataclass
class DashboardSnapshot:
    total_trades: int
    total_pnl: Decimal
    win_rate: Decimal
    equity: Decimal
    drawdown: Decimal
