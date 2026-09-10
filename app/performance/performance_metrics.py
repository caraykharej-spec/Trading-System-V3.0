"""Performance metrics foundation."""

from dataclasses import dataclass


@dataclass
class PerformanceSnapshot:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades


class PerformanceMetrics:
    def calculate_drawdown(self, peak_equity: float, current_equity: float) -> float:
        if peak_equity <= 0:
            return 0.0
        return (peak_equity - current_equity) / peak_equity
