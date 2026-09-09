from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Generic, TypeVar

from app.data.market_data import Candle

from .engine import BacktestEngine
from .models import BacktestConfig, BacktestResult

T = TypeVar("T")


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
    """Walk-forward runner that evaluates each test segment independently."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(self, symbol: str, candles_by_timeframe: dict[str, list[Candle]], train_size: int, test_size: int, step: int | None = None) -> WalkForwardResult:
        source_15m = candles_by_timeframe.get("15m", [])
        windows = build_windows(len(source_15m), train_size, test_size, step)
        results: list[BacktestResult] = []
        for window in windows:
            segment: dict[str, list[Candle]] = {}
            for timeframe, rows in candles_by_timeframe.items():
                test_start_time = source_15m[window.test_start].timestamp
                test_end_time = source_15m[window.test_end - 1].timestamp
                segment[timeframe] = [c for c in rows if test_start_time <= c.timestamp <= test_end_time]
            if all(segment.get(tf) for tf in ("1d", "4h", "1h", "15m")):
                results.append(BacktestEngine(self.config).run(symbol, segment))
        return WalkForwardResult(windows=windows, results=tuple(results))
