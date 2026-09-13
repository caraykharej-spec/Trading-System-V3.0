from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import monotonic
from typing import Callable, Iterable

from app.application.strategy_pipeline import (
    SnapshotLoader,
    StrategyRejection,
)
from app.data.providers.http import ProviderError
from app.strategy.strategy_engine import StrategySignal, evaluate_strategy


@dataclass(frozen=True)
class ScanProgressEvent:
    event: str
    symbol: str | None
    completed: int
    total: int
    attempt: int
    elapsed_seconds: float


@dataclass(frozen=True)
class BudgetedScanResult:
    evaluated: int
    signals: tuple[StrategySignal, ...]
    rejections: tuple[StrategyRejection, ...]
    retried: tuple[str, ...]
    budget_exceeded: bool
    elapsed_seconds: float


ProgressReporter = Callable[[ScanProgressEvent], None]


def _is_retryable(rejection: StrategyRejection) -> bool:
    reason = "|".join(rejection.reasons).lower()
    return rejection.state == "DATA_ERROR" and any(
        marker in reason
        for marker in (
            "all_sources_failed",
            "timeout",
            "rate",
            "circuit_open",
            "insufficient_cached_history",
            "latency_budget_exceeded",
        )
    )


class BudgetedMarketScanner:
    """Bounded concurrent scan with progress and end-of-pass retries."""

    def __init__(
        self,
        snapshot_loader: SnapshotLoader,
        *,
        max_workers: int = 16,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.snapshot_loader = snapshot_loader
        self.max_workers = max_workers
        self.clock = clock

    def run(
        self,
        symbols: Iterable[str],
        *,
        budget_seconds: float,
        retry_attempts: int = 1,
        progress: ProgressReporter | None = None,
    ) -> BudgetedScanResult:
        if budget_seconds <= 0:
            raise ValueError("budget_seconds must be positive")
        if retry_attempts < 0:
            raise ValueError("retry_attempts cannot be negative")
        ordered = tuple(symbols)
        started = self.clock()
        deadline = started + budget_seconds
        completed = 0

        def emit(event: str, symbol: str | None, attempt: int) -> None:
            if progress is not None:
                progress(
                    ScanProgressEvent(
                        event,
                        symbol,
                        completed,
                        len(ordered),
                        attempt,
                        self.clock() - started,
                    )
                )

        def evaluate(symbol: str, attempt: int) -> StrategySignal | StrategyRejection:
            nonlocal completed
            emit("MARKET_STARTED", symbol, attempt)
            if self.clock() >= deadline:
                completed += 1
                emit("MARKET_BUDGET_EXCEEDED", symbol, attempt)
                return StrategyRejection(
                    symbol,
                    ("time_budget_exceeded",),
                    state="DATA_ERROR",
                )
            try:
                daily, four_hour, one_hour, fifteen = self.snapshot_loader(symbol)
                signal = evaluate_strategy(daily, four_hour, one_hour, fifteen)
            except (ValueError, KeyError, ProviderError) as exc:
                completed += 1
                emit("MARKET_FAILED", symbol, attempt)
                return StrategyRejection(
                    symbol,
                    (str(exc) or exc.__class__.__name__,),
                    state="DATA_ERROR",
                )
            completed += 1
            emit("MARKET_COMPLETED", symbol, attempt)
            if signal.state.value == "READY_FOR_RISK_REVIEW":
                return signal
            return StrategyRejection(
                symbol,
                signal.reasons or (f"strategy state is {signal.state.value}",),
                signal.score,
                signal.confidence,
                signal.state.value,
            )

        def evaluate_many(
            selected: tuple[str, ...], attempt: int
        ) -> tuple[StrategySignal | StrategyRejection, ...]:
            if not selected:
                return ()
            workers = min(self.max_workers, len(selected))
            if workers == 1:
                return (evaluate(selected[0], attempt),)
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="budgeted-market",
            ) as executor:
                return tuple(executor.map(lambda symbol: evaluate(symbol, attempt), selected))

        first = evaluate_many(ordered, 1)
        by_symbol = dict(zip(ordered, first, strict=True))
        retried: list[str] = []
        for attempt in range(2, retry_attempts + 2):
            retry_symbols = tuple(
                symbol
                for symbol in ordered
                if isinstance(by_symbol[symbol], StrategyRejection)
                and _is_retryable(by_symbol[symbol])
                and self.clock() < deadline
            )
            if not retry_symbols:
                break
            retried.extend(retry_symbols)
            emit("RETRY_QUEUED", None, attempt)
            retried_results = evaluate_many(retry_symbols, attempt)
            by_symbol.update(zip(retry_symbols, retried_results, strict=True))

        signals = sorted(
            (
                result
                for result in by_symbol.values()
                if isinstance(result, StrategySignal)
            ),
            key=lambda item: (item.score, item.confidence, item.rr),
            reverse=True,
        )
        rejections = tuple(
            by_symbol[symbol]
            for symbol in ordered
            if isinstance(by_symbol[symbol], StrategyRejection)
        )
        elapsed = self.clock() - started
        emit("SCAN_COMPLETED", None, retry_attempts + 1)
        return BudgetedScanResult(
            len(ordered),
            tuple(signals),
            rejections,
            tuple(retried),
            elapsed >= budget_seconds,
            elapsed,
        )
