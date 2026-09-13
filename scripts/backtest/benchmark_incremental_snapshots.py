from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from app.backtest.engine import BacktestEngine
from app.data.market_data import Candle

_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}


class ReferenceBacktestEngine(BacktestEngine):
    def _snapshots_at(self, symbol, candles, decision_time):  # type: ignore[no-untyped-def]
        return self._snapshots_at_reference(symbol, candles, decision_time)


def _series(timeframe: str, count: int, end: datetime) -> list[Candle]:
    step = timedelta(minutes=_MINUTES[timeframe])
    start = end - step * count
    rows: list[Candle] = []
    for index in range(count):
        anchor = (
            Decimal("100")
            + Decimal(index) * Decimal("0.13")
            + Decimal((index % 11) - 5) * Decimal("0.09")
        )
        close = anchor + Decimal((index % 7) - 3) * Decimal("0.05")
        rows.append(
            Candle(
                symbol="BTC/USDT",
                timeframe=timeframe,
                timestamp=start + step * index,
                open=anchor,
                high=max(anchor, close) + Decimal("1.20"),
                low=min(anchor, close) - Decimal("1.10"),
                close=close,
                volume=Decimal("1000") + Decimal(index % 19) * Decimal("17"),
            )
        )
    return rows


def _signature(result):  # type: ignore[no-untyped-def]
    trades = [
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
    return (
        result.initial_equity,
        result.final_equity,
        result.rejected_signals,
        result.open_positions_at_end,
        result.max_drawdown_percent,
        result.win_rate_percent,
        result.profit_factor,
        result.total_return_percent,
        result.max_concurrent_positions,
        trades,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=400)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.bars < 220:
        raise ValueError("bars must be at least 220 so EMA200 is exercised")

    end = datetime(2026, 9, 1, tzinfo=timezone.utc)
    candles = {
        timeframe: _series(timeframe, args.bars, end)
        for timeframe in _MINUTES
    }

    reference_started = perf_counter()
    reference = ReferenceBacktestEngine().run("BTC/USDT", candles)
    reference_seconds = perf_counter() - reference_started

    incremental_started = perf_counter()
    incremental = BacktestEngine().run("BTC/USDT", candles)
    incremental_seconds = perf_counter() - incremental_started

    equivalent = _signature(reference) == _signature(incremental)
    if not equivalent:
        raise RuntimeError("incremental benchmark result diverged from reference")

    speedup = (
        reference_seconds / incremental_seconds
        if incremental_seconds > 0
        else None
    )
    report = {
        "symbol": "BTC/USDT",
        "bars_per_timeframe": args.bars,
        "reference_seconds": reference_seconds,
        "incremental_seconds": incremental_seconds,
        "speedup_ratio": speedup,
        "equivalent": equivalent,
        "trade_count": len(incremental.trades),
        "rejected_signals": incremental.rejected_signals,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print("LONG-HORIZON SNAPSHOT BENCHMARK COMPLETE")
    print(f"equivalent={equivalent}")
    print(f"reference_seconds={reference_seconds:.6f}")
    print(f"incremental_seconds={incremental_seconds:.6f}")
    print(f"speedup_ratio={speedup}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
