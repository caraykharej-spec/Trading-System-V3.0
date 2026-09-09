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
    """Runs the deterministic strategy stage without risk or execution.

    The strategy stage produces candidates in descending opportunity quality.
    Risk and portfolio approval are downstream hard gates and must be applied
    before the final Top-N list is presented to a user.
    """

    def __init__(self, snapshot_loader: SnapshotLoader) -> None:
        self.snapshot_loader = snapshot_loader

    @staticmethod
    def _rank(signals: list[StrategySignal]) -> list[StrategySignal]:
        signals.sort(
            key=lambda signal: (signal.score, signal.confidence, signal.rr),
            reverse=True,
        )
        return signals

    def evaluate_all(self, symbols: Iterable[str]) -> tuple[int, tuple[StrategySignal, ...]]:
        signals: list[StrategySignal] = []
        evaluated = 0
        for symbol in symbols:
            evaluated += 1
            try:
                daily, four_hour, one_hour, fifteen = self.snapshot_loader(symbol)
                signal = evaluate_strategy(daily, four_hour, one_hour, fifteen)
            except (ValueError, KeyError):
                continue
            if signal.state.value == "READY_FOR_RISK_REVIEW":
                signals.append(signal)
        return evaluated, tuple(self._rank(signals))

    def evaluate(self, symbols: Iterable[str], top_n: int = 10) -> StrategyPipelineResult:
        if top_n < 1:
            raise ValueError("top_n must be positive")
        evaluated, signals = self.evaluate_all(symbols)
        selected = tuple(
            Opportunity(signal=signal, rank=index)
            for index, signal in enumerate(signals[:top_n], start=1)
        )
        return StrategyPipelineResult(evaluated=evaluated, qualified=selected)
