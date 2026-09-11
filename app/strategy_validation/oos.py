from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.backtest.engine import BacktestEngine
from app.backtest.models import BacktestConfig, BacktestResult
from app.data.market_data import Candle
from app.strategy.rules import DEFAULT_RULES, StrategyRules


@dataclass(frozen=True)
class ChronologicalSplit:
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    holdout_start: datetime
    holdout_end: datetime


@dataclass(frozen=True)
class OutOfSampleResult:
    split: ChronologicalSplit
    training: BacktestResult
    validation: BacktestResult
    holdout: BacktestResult


def build_chronological_split(
    anchor_candles: list[Candle],
    *,
    train_size: int,
    validation_size: int,
) -> ChronologicalSplit:
    ordered = sorted(anchor_candles, key=lambda candle: candle.timestamp)
    if train_size <= 0 or validation_size <= 0:
        raise ValueError("train_size and validation_size must be positive")
    if len(ordered) <= train_size + validation_size:
        raise ValueError("anchor dataset does not leave a non-empty holdout segment")
    if len({candle.timestamp for candle in ordered}) != len(ordered):
        raise ValueError("anchor dataset contains duplicate timestamps")

    train_end_index = train_size - 1
    validation_start_index = train_size
    validation_end_index = train_size + validation_size - 1
    holdout_start_index = train_size + validation_size

    return ChronologicalSplit(
        train_start=ordered[0].timestamp,
        train_end=ordered[train_end_index].timestamp,
        validation_start=ordered[validation_start_index].timestamp,
        validation_end=ordered[validation_end_index].timestamp,
        holdout_start=ordered[holdout_start_index].timestamp,
        holdout_end=ordered[-1].timestamp,
    )


def _history_until(
    candles_by_timeframe: dict[str, list[Candle]],
    *,
    symbol: str,
    end: datetime,
) -> dict[str, list[Candle]]:
    return {
        timeframe: sorted(
            [
                candle
                for candle in rows
                if candle.symbol == symbol and candle.timestamp <= end
            ],
            key=lambda candle: candle.timestamp,
        )
        for timeframe, rows in candles_by_timeframe.items()
    }


def run_out_of_sample_validation(
    symbol: str,
    candles_by_timeframe: dict[str, list[Candle]],
    *,
    train_size: int,
    validation_size: int,
    config: BacktestConfig | None = None,
    rules: StrategyRules = DEFAULT_RULES,
) -> OutOfSampleResult:
    anchor = [
        candle
        for candle in candles_by_timeframe.get("15m", [])
        if candle.symbol == symbol
    ]
    split = build_chronological_split(
        anchor,
        train_size=train_size,
        validation_size=validation_size,
    )
    active_config = config or BacktestConfig()
    engine = BacktestEngine(active_config, rules=rules)

    training_data = _history_until(
        candles_by_timeframe,
        symbol=symbol,
        end=split.train_end,
    )
    validation_data = _history_until(
        candles_by_timeframe,
        symbol=symbol,
        end=split.validation_end,
    )
    holdout_data = _history_until(
        candles_by_timeframe,
        symbol=symbol,
        end=split.holdout_end,
    )

    training = engine.run(symbol, training_data)
    validation = engine.run(
        symbol,
        validation_data,
        evaluation_start=split.validation_start,
    )
    holdout = engine.run(
        symbol,
        holdout_data,
        evaluation_start=split.holdout_start,
    )
    return OutOfSampleResult(split, training, validation, holdout)
