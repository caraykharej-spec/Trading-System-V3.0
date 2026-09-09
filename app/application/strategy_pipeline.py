from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from app.market.analysis import MarketSnapshot
from app.strategy.strategy_engine import StrategySignal, evaluate_strategy


@dataclass(frozen=True)
class Opportunity:
    signal: StrategySignal
    rank: int


@dataclass(frozen=True)
class StrategyPipelineResult:
    evaluated: int
    qualified: tuple[Opportunity, ...]


SnapshotLoader = Callable[[str], tuple[MarketSnapshot, MarketSnapshot, MarketSnapshot, MarketSnapshot]]


class StrategyPipeline:
    """Runs the deterministic strategy stage without executing orders.

    Risk and portfolio approval remain explicit downstream gates. This class
    only turns complete multi-timeframe market snapshots into qualified
    strategy opportunities and ranks them for later risk review.
    """

    def __init__(self, snapshot_loader: SnapshotLoader) -> None:
        self.snapshot_loader = snapshot_loader

    def evaluate(self, symbols: Iterable[str], top_n: int = 10) -> StrategyPipelineResult:
        if top_n < 1:
            raise ValueError("top_n must be positive")

        opportunities: list[StrategySignal] = []
        evaluated = 0
        for symbol in symbols:
            evaluated += 1
            try:
                daily, four_hour, one_hour, fifteen = self.snapshot_loader(symbol)
                signal = evaluate_strategy(daily, four_hour, one_hour, fifteen)
            except (ValueError, KeyError):
                continue
            if signal.state.value == "READY_FOR_RISK_REVIEW":
                opportunities.append(signal)

        opportunities.sort(
            key=lambda signal: (signal.score, signal.confidence, signal.rr),
            reverse=True,
        )
        selected = tuple(
            Opportunity(signal=signal, rank=index)
            for index, signal in enumerate(opportunities[:top_n], start=1)
        )
        return StrategyPipelineResult(evaluated=evaluated, qualified=selected)
