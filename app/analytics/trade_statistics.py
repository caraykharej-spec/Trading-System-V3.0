from decimal import Decimal


class TradeStatistics:
    def calculate(self, trades: list[dict]) -> dict:
        total = len(trades)
        wins = sum(1 for t in trades if Decimal(str(t.get("pnl", 0))) > 0)
        return {
            "total_trades": total,
            "winning_trades": wins,
            "losing_trades": total - wins,
        }
