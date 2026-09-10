from dataclasses import dataclass
from decimal import Decimal


@dataclass
class AnalyticsSnapshot:
    total_trades: int
    total_pnl: Decimal
    win_rate: Decimal


class AnalyticsEngine:
    def generate_snapshot(self, trades: list[dict]) -> AnalyticsSnapshot:
        total = len(trades)
        pnl = sum((Decimal(str(t.get("pnl", 0))) for t in trades), Decimal("0"))
        wins = sum(1 for t in trades if Decimal(str(t.get("pnl", 0))) > 0)
        win_rate = Decimal("0") if total == 0 else Decimal(wins) / Decimal(total)
        return AnalyticsSnapshot(total, pnl, win_rate)
