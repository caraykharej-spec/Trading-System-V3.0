from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.backtest.locked_dataset import run_locked_dataset_backtest
from app.data.historical_backfill import HistoricalBackfillPolicy, collect_historical_dataset
from app.data.market_data import Candle
from app.data.providers.gateio import GateIOProvider
from app.data.quality import timeframe_seconds

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_END = datetime(2026, 1, 4, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _FakeGateProvider(GateIOProvider):
    calls: list[tuple[str, datetime, datetime]] = field(default_factory=list)

    def get_candles_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        self.calls.append((timeframe, start, end))
        step = timedelta(seconds=timeframe_seconds(timeframe))
        rows: list[Candle] = []
        cursor = start
        index = 0
        while cursor <= end:
            base = Decimal("100") + Decimal(index) * Decimal("0.01")
            rows.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=cursor,
                    open=base,
                    high=base + Decimal("1"),
                    low=base - Decimal("1"),
                    close=base + Decimal("0.10"),
                    volume=Decimal("1000"),
                )
            )
            cursor += step
            index += 1
        return rows


def test_locked_dataset_entrypoint_verifies_and_runs(tmp_path) -> None:
    collected = collect_historical_dataset(
        symbol="BTC/USDT",
        start=_START,
        end=_END,
        output_dir=tmp_path,
        dataset_version="1.0.0",
        provider=_FakeGateProvider(),
        policy=HistoricalBackfillPolicy(
            chunk_points=1000,
            retry_backoff_seconds=0,
        ),
        code_revision="c" * 40,
        sleep_fn=lambda _: None,
    )

    evidence = run_locked_dataset_backtest(tmp_path)

    assert evidence.symbol == "BTC/USDT"
    assert evidence.dataset_bundle_fingerprint == collected.manifest[
        "dataset_bundle_fingerprint"
    ]
    assert evidence.manifest_fingerprint == collected.manifest["manifest_fingerprint"]
    assert evidence.code_revision == "c" * 40
    assert evidence.result.initial_equity == Decimal("10000")
