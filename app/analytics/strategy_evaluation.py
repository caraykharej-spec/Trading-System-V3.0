from dataclasses import dataclass


@dataclass
class StrategyEvaluation:
    strategy_name: str
    total_trades: int
    total_pnl: float
    win_rate: float
    profit_factor: float
    expectancy: float


class StrategyEvaluator:
    def evaluate(self, strategy_name: str, trades: list[dict]) -> StrategyEvaluation:
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) < 0]

        total_pnl = sum(t.get("pnl", 0) for t in trades)
        gross_profit = sum(t.get("pnl", 0) for t in wins)
        gross_loss = abs(sum(t.get("pnl", 0) for t in losses))

        profit_factor = gross_profit / gross_loss if gross_loss else 0
        win_rate = len(wins) / len(trades) if trades else 0
        expectancy = total_pnl / len(trades) if trades else 0

        return StrategyEvaluation(
            strategy_name=strategy_name,
            total_trades=len(trades),
            total_pnl=total_pnl,
            win_rate=win_rate,
            profit_factor=profit_factor,
            expectancy=expectancy,
        )
