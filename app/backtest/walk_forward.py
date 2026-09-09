from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.data.market_data import Candle

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


def build_windows(length: int, train_size: int, test_size: int, step: int | None = None) -> tuple[WalkForwardWindow, ...]:
    if length <= 0 or train_size <= 0 or test_size <= 0:
        raise ValueError("length, train_size and test_size must be positive")
    step = step or test_size
    if step <= 0:
        raise ValueError("step must be positive")
    windows: list[WalkForwardWindow] = []
    start = 0
    while start + train_size + test_size <= length:
        windows.append(WalkForwardWindow(start, start + train_size, start + train_size, start + train_size + test_size))
        start += step
    return tuple(windows)


class WalkForwardRunner:
    """Leakage-safe train/optimize/test runner.

    The training period is used only to select a configuration through the
    optional optimizer. The selected configuration is then frozen for the OOS
    test period. Higher-timeframe history before the OOS boundary is retained
    as warm-up data, while ``evaluation_start`` prevents pre-test trades from
    contaminating OOS metrics.
    """

    def __init__(self, config: BacktestConfig | None = None, optimizer: Optimizer | None = None) -> None:
        self.config = config or BacktestConfig()
        self.optimizer = optimizer

    def run(
        self,
        symbol: str,
        candles_by_timeframe: dict[str, list[Candle]],
        train_size: int,
        test_size: int,
        step: int | None = None,
    ) -> WalkForwardResult:
        source_15m = sorted(candles_by_timeframe.get("15m", []), key=lambda c: c.timestamp)
        windows = build_windows(len(source_15m), train_size, test_size, step)
        results: list[BacktestResult] = []

        for window in windows:
            train_start = source_15m[window.train_start].timestamp
            train_end = source_15m[window.train_end - 1].timestamp
            test_start = source_15m[window.test_start].timestamp
            test_end = source_15m[window.test_end - 1].timestamp

            # Retain all history through the test endpoint. This supplies the
            # indicator warm-up needed by 1h/4h/1d analysis without allowing it
            # to create trades before the requested evaluation boundary.
            segment = {
                timeframe: sorted(
                    [c for c in rows if c.symbol == symbol and c.timestamp <= test_end],
                    key=lambda c: c.timestamp,
                )
                for timeframe, rows in candles_by_timeframe.items()
            }
            if not all(segment.get(tf) for tf in ("1d", "4h", "1h", "15m")):
                continue

            train_result = BacktestEngine(self.config).run(symbol, segment, evaluation_start=train_start)
            selected_config = self.optimizer(train_result, self.config) if self.optimizer else self.config
            if not isinstance(selected_config, BacktestConfig):
                raise TypeError("optimizer must return BacktestConfig")

            oos_result = BacktestEngine(selected_config).run(symbol, segment, evaluation_start=test_start)
            results.append(oos_result)

        return WalkForwardResult(windows=windows, results=tuple(results))
