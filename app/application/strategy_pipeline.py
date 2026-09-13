from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

from app.data.providers.http import ProviderError
from app.market.analysis import MarketSnapshot
from app.strategy.strategy_engine import StrategySignal, evaluate_strategy


@dataclass(frozen=True)
class Opportunity:
    signal: StrategySignal
    rank: int


@dataclass(frozen=True)
class StrategyRejection:
    symbol: str
    reasons: tuple[str, ...]
    score: Decimal | None = None
    confidence: Decimal | None = None
    state: str = "DATA_ERROR"


@dataclass(frozen=True)
class StrategyPipelineResult:
    evaluated: int
    qualified: tuple[Opportunity, ...]
    rejected: tuple[StrategyRejection, ...] = ()


SnapshotLoader = Callable[
    [str], tuple[MarketSnapshot, MarketSnapshot, MarketSnapshot, MarketSnapshot]
]


class StrategyPipeline:
    """Runs the deterministic strategy stage without risk or execution.

    The strategy stage produces candidates in descending opportunity quality.
    Risk and portfolio approval are downstream hard gates and must be applied
    before the final Top-N list is presented to a user.
    """

    def __init__(self, snapshot_loader: SnapshotLoader, *, max_workers: int = 16) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.snapshot_loader = snapshot_loader
        self.max_workers = max_workers

    @staticmethod
    def _rank(signals: list[StrategySignal]) -> list[StrategySignal]:
        signals.sort(
            key=lambda signal: (signal.score, signal.confidence, signal.rr),
            reverse=True,
        )
        return signals

    def evaluate_all_with_rejections(
        self,
        symbols: Iterable[str],
    ) -> tuple[int, tuple[StrategySignal, ...], tuple[StrategyRejection, ...]]:
        symbol_list = list(symbols)
        if not symbol_list:
            return 0, (), ()

        def evaluate_symbol(
            symbol: str,
        ) -> StrategySignal | StrategyRejection:
            try:
                daily, four_hour, one_hour, fifteen = self.snapshot_loader(symbol)
            except (ValueError, KeyError, ProviderError) as exc:
                reason = str(exc) or exc.__class__.__name__
                return StrategyRejection(symbol=symbol, reasons=(reason,))
            try:
                signal = evaluate_strategy(daily, four_hour, one_hour, fifteen)
            except ValueError as exc:
                reason = str(exc) or exc.__class__.__name__
                return StrategyRejection(
                    symbol=symbol,
                    reasons=(reason,),
                    state="NO_TRADE",
                )
            if signal.state.value == "READY_FOR_RISK_REVIEW":
                return signal
            reasons = signal.reasons or (f"strategy state is {signal.state.value}",)
            return StrategyRejection(
                symbol=symbol,
                reasons=reasons,
                score=signal.score,
                confidence=signal.confidence,
                state=signal.state.value,
            )

        worker_count = min(self.max_workers, len(symbol_list))
        results: tuple[StrategySignal | StrategyRejection, ...]
        if worker_count == 1:
            results = (evaluate_symbol(symbol_list[0]),)
        else:
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="signal-market",
            ) as executor:
                results = tuple(executor.map(evaluate_symbol, symbol_list))

        signals: list[StrategySignal] = []
        rejections: list[StrategyRejection] = []
        for result in results:
            if isinstance(result, StrategyRejection):
                rejections.append(result)
            else:
                signals.append(result)
        return len(symbol_list), tuple(self._rank(signals)), tuple(rejections)

    def evaluate_all(self, symbols: Iterable[str]) -> tuple[int, tuple[StrategySignal, ...]]:
        evaluated, signals, _ = self.evaluate_all_with_rejections(symbols)
        return evaluated, signals

    def evaluate(self, symbols: Iterable[str], top_n: int = 10) -> StrategyPipelineResult:
        if top_n < 1:
            raise ValueError("top_n must be positive")
        evaluated, signals, rejections = self.evaluate_all_with_rejections(symbols)
        selected = tuple(
            Opportunity(signal=signal, rank=index)
            for index, signal in enumerate(signals[:top_n], start=1)
        )
        return StrategyPipelineResult(
            evaluated=evaluated,
            qualified=selected,
            rejected=rejections,
        )
