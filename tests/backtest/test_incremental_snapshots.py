from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.backtest.engine import BacktestEngine
from app.backtest.incremental_snapshots import (
    IncrementalMarketState,
    IncrementalSnapshotCursor,
)
from app.data.market_data import Candle
from app.market.analysis import analyze_market

_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def _series(
    timeframe: str,
    count: int,
    start: datetime,
    *,
    symbol: str = "BTC/USDT",
) -> list[Candle]:
    step = timedelta(minutes=_MINUTES[timeframe])
    rows: list[Candle] = []
    for index in range(count):
        anchor = (
            Decimal("100")
            + Decimal(index) * Decimal("0.17")
            + Decimal((index % 9) - 4) * Decimal("0.11")
        )
        close = anchor + Decimal((index % 5) - 2) * Decimal("0.07")
        high = max(anchor, close) + Decimal("1.25")
        low = min(anchor, close) - Decimal("1.15")
        rows.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=start + step * index,
                open=anchor,
                high=high,
                low=low,
                close=close,
                volume=Decimal("1000") + Decimal(index % 17) * Decimal("13"),
            )
        )
    return rows


def _history_ending(
    timeframe: str,
    count: int,
    end: datetime,
) -> list[Candle]:
    step = timedelta(minutes=_MINUTES[timeframe])
    return _series(timeframe, count, end - step * count)


def test_incremental_market_state_matches_reference_snapshots() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = _series("15m", 260, start)
    checkpoints = {2, 15, 16, 20, 34, 50, 200, 201, 220, 260}
    state = IncrementalMarketState("BTC/USDT", "15m")

    for index, candle in enumerate(candles, start=1):
        actual = state.push(candle)
        if index in checkpoints:
            expected = analyze_market("BTC/USDT", "15m", candles[:index])
            assert actual == expected


def test_incremental_cursor_excludes_incomplete_future_candles() -> None:
    decision_time = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    base: dict[str, list[Candle]] = {}
    changed: dict[str, list[Candle]] = {}

    for timeframe, minutes in _MINUTES.items():
        duration = timedelta(minutes=minutes)
        start = decision_time - duration * 2
        rows = _series(timeframe, 3, start)
        future = rows[-1]
        altered = Candle(
            symbol=future.symbol,
            timeframe=future.timeframe,
            timestamp=future.timestamp,
            open=Decimal("999999"),
            high=Decimal("1000001"),
            low=Decimal("999998"),
            close=Decimal("1000000"),
            volume=Decimal("999999"),
        )
        base[timeframe] = rows
        changed[timeframe] = [*rows[:-1], altered]

    original = IncrementalSnapshotCursor("BTC/USDT", base).snapshots_at(decision_time)
    mutated_future = IncrementalSnapshotCursor("BTC/USDT", changed).snapshots_at(
        decision_time
    )

    assert original == mutated_future


class _ReferenceBacktestEngine(BacktestEngine):
    def _snapshots_at(
        self,
        symbol: str,
        candles: dict[str, list[Candle]],
        decision_time: datetime,
    ):  # type: ignore[no-untyped-def]
        return self._snapshots_at_reference(symbol, candles, decision_time)


def _trade_signature(result):  # type: ignore[no-untyped-def]
    return [
        (
            trade.symbol,
            trade.direction,
            trade.setup,
            trade.entry_time,
            trade.entry_price,
            trade.exit_time,
            trade.exit_price,
            trade.stop_loss,
            trade.target,
            trade.quantity,
            trade.total_amount,
            trade.leverage,
            trade.realized_pnl,
            trade.commission,
            trade.funding_cost,
            trade.exit_reason,
        )
        for trade in result.trades
    ]


def test_backtest_result_matches_reference_snapshot_path() -> None:
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)
    candles = {
        timeframe: _history_ending(timeframe, 220, end)
        for timeframe in _MINUTES
    }

    fast = BacktestEngine().run("BTC/USDT", candles)
    reference = _ReferenceBacktestEngine().run("BTC/USDT", candles)

    assert fast.initial_equity == reference.initial_equity
    assert fast.final_equity == reference.final_equity
    assert fast.rejected_signals == reference.rejected_signals
    assert fast.open_positions_at_end == reference.open_positions_at_end
    assert fast.max_drawdown_percent == reference.max_drawdown_percent
    assert fast.win_rate_percent == reference.win_rate_percent
    assert fast.profit_factor == reference.profit_factor
    assert fast.total_return_percent == reference.total_return_percent
    assert fast.max_concurrent_positions == reference.max_concurrent_positions
    assert _trade_signature(fast) == _trade_signature(reference)


def test_cursor_can_rewind_without_reusing_future_state() -> None:
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)
    candles = {
        timeframe: _history_ending(timeframe, 20, end)
        for timeframe in _MINUTES
    }
    cursor = IncrementalSnapshotCursor("BTC/USDT", candles)

    later = cursor.snapshots_at(end)
    earlier_time = end - timedelta(days=2)
    rewound = cursor.snapshots_at(earlier_time)
    fresh = IncrementalSnapshotCursor("BTC/USDT", candles).snapshots_at(earlier_time)

    assert later is not None
    assert rewound == fresh
