from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.data.market_data import Candle
from app.strategy.rules import DEFAULT_RULES, StrategyRules

from .engine import BacktestEngine
from .models import BacktestConfig, BacktestResult


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: int
    train_end: int
    test_start: int
    test_end: int


@dataclass(frozen=True)
class WalkForwardResult:
    windows: tuple[WalkForwardWindow, ...]
    results: tuple[BacktestResult, ...]


Optimizer = Callable[[BacktestResult, BacktestConfig], BacktestConfig]


def build_windows(
    length: int,
    train_size: int,
    test_size: int,
    step: int | None = None,
) -> tuple[WalkForwardWindow, ...]:
    if length <= 0 or train_size <= 0 or test_size <= 0:
        raise ValueError("length, train_size and test_size must be positive")
    step = test_size if step is None else step
    if step <= 0:
        raise ValueError("step must be positive")
    windows: list[WalkForwardWindow] = []
    start = 0
    while start + train_size + test_size <= length:
        windows.append(
            WalkForwardWindow(
                start,
                start + train_size,
                start + train_size,
                start + train_size + test_size,
            )
        )
        start += step
    return tuple(windows)


class WalkForwardRunner:
    """Leakage-safe rolling train/optimize/OOS evaluation."""

    def __init__(
        self,
        config: BacktestConfig | None = None,
        optimizer: Optimizer | None = None,
        *,
        rules: StrategyRules = DEFAULT_RULES,
    ) -> None:
        self.config = config or BacktestConfig()
        self.optimizer = optimizer
        self.rules = rules

    def run(
        self,
        symbol: str,
        candles_by_timeframe: dict[str, list[Candle]],
        train_size: int,
        test_size: int,
        step: int | None = None,
    ) -> WalkForwardResult:
        source_15m = sorted(
            candles_by_timeframe.get("15m", []), key=lambda candle: candle.timestamp
        )
        windows = build_windows(len(source_15m), train_size, test_size, step)
        results: list[BacktestResult] = []
        required = ("1d", "4h", "1h", "15m")

        for window in windows:
            train_start = source_15m[window.train_start].timestamp
            train_end = source_15m[window.train_end - 1].timestamp
            test_start = source_15m[window.test_start].timestamp
            test_end = source_15m[window.test_end - 1].timestamp

            train_segment = {
                timeframe: sorted(
                    [
                        candle
                        for candle in rows
                        if candle.symbol == symbol
                        and train_start <= candle.timestamp <= train_end
                    ],
                    key=lambda candle: candle.timestamp,
                )
                for timeframe, rows in candles_by_timeframe.items()
            }
            oos_segment = {
                timeframe: sorted(
                    [
                        candle
                        for candle in rows
                        if candle.symbol == symbol and candle.timestamp <= test_end
                    ],
                    key=lambda candle: candle.timestamp,
                )
                for timeframe, rows in candles_by_timeframe.items()
            }
            if not all(train_segment.get(timeframe) for timeframe in required) or not all(
                oos_segment.get(timeframe) for timeframe in required
            ):
                continue

            train_result = BacktestEngine(self.config, rules=self.rules).run(
                symbol, train_segment
            )
            selected = (
                self.optimizer(train_result, self.config)
                if self.optimizer
                else self.config
            )
            if not isinstance(selected, BacktestConfig):
                raise TypeError("optimizer must return BacktestConfig")

            oos_result = BacktestEngine(selected, rules=self.rules).run(
                symbol,
                oos_segment,
                evaluation_start=test_start,
            )
            results.append(oos_result)

        return WalkForwardResult(windows=windows, results=tuple(results))
