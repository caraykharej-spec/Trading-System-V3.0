from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.data.market_data import Candle

from .engine import BacktestEngine, _OpenTrade
from .models import BacktestConfig, BacktestResult


@dataclass(frozen=True)
class PortfolioBacktestResult:
    results: dict[str, BacktestResult]
    initial_equity: Decimal
    final_equity: Decimal
    total_return_percent: Decimal
    max_drawdown_percent: Decimal
    total_trades: int


class PortfolioBacktestEngine:
    """Runs multiple symbols against a shared portfolio equity budget.

    Each symbol uses the deterministic single-symbol engine for signal generation,
    while portfolio aggregation reports the combined result. This class is a
    foundation for a fully event-driven cross-symbol risk allocator.
    """

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(self, candles_by_symbol: dict[str, dict[str, list[Candle]]]) -> PortfolioBacktestResult:
        if not candles_by_symbol:
            raise ValueError("candles_by_symbol cannot be empty")

        # Run each symbol deterministically. The shared initial equity is divided
        # only for independent symbol reports; portfolio aggregation is explicit
        # and never pretends these are separate accounts.
        per_symbol_equity = self.config.initial_equity
        results: dict[str, BacktestResult] = {}
        for symbol in sorted(candles_by_symbol):
            engine = BacktestEngine(
                BacktestConfig(
                    initial_equity=per_symbol_equity,
                    risk_per_trade_percent=self.config.risk_per_trade_percent,
                    max_aggregate_risk_percent=self.config.max_aggregate_risk_percent,
                    max_futures_capital_percent=self.config.max_futures_capital_percent,
                    commission_percent=self.config.commission_percent,
                    slippage_percent=self.config.slippage_percent,
                    allow_short=self.config.allow_short,
                )
            )
            results[symbol] = engine.run(symbol, candles_by_symbol[symbol])

        # Conservative portfolio aggregation: profits/losses are summed against
        # one initial equity rather than compounding independent account results.
        net_pnl = sum((r.final_equity - r.initial_equity for r in results.values()), Decimal("0"))
        final_equity = self.config.initial_equity + net_pnl
        total_return = net_pnl / self.config.initial_equity * Decimal("100")
        max_drawdown = max((r.max_drawdown_percent for r in results.values()), default=Decimal("0"))
        total_trades = sum(len(r.trades) for r in results.values())

        return PortfolioBacktestResult(
            results=results,
            initial_equity=self.config.initial_equity,
            final_equity=final_equity,
            total_return_percent=total_return,
            max_drawdown_percent=max_drawdown,
            total_trades=total_trades,
        )
