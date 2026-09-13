from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.data.historical_backfill import (
    HistoricalBackfillPolicy,
    collect_historical_dataset,
    load_locked_dataset,
)
from app.data.market_data import Candle
from app.data.providers.gateio import GateIOProvider
from app.data.providers.http import ProviderError
from app.data.quality import timeframe_seconds

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 4, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FakeGateProvider(GateIOProvider):
    calls: list[tuple[str, datetime, datetime]] = field(default_factory=list)
    failures_remaining: list[int] = field(default_factory=lambda: [0])

    def get_candles_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        self.calls.append((timeframe, start, end))
        if self.failures_remaining[0] > 0:
            self.failures_remaining[0] -= 1
            raise ProviderError("transient")
        step = timedelta(seconds=timeframe_seconds(timeframe))
        rows: list[Candle] = []
        cursor = start
        while cursor <= end:
            sequence = Decimal(str(int(cursor.timestamp())))
            base = Decimal("100") + (sequence % Decimal("1000")) / Decimal("1000")
            rows.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=cursor,
                    open=base,
                    high=base + Decimal("1"),
                    low=base - Decimal("1"),
                    close=base + Decimal("0.25"),
                    volume=Decimal("1000"),
                )
            )
            cursor += step
        return rows


class RecordingHttpClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_json(self, url: str):
        self.urls.append(url)
        return [
            [
                str(int(START.timestamp())),
                "10",
                "100.25",
                "101",
                "99",
                "100",
            ]
        ]


def test_backfill_checkpoints_resume_without_network_refetch(tmp_path):
    provider = FakeGateProvider()
    policy = HistoricalBackfillPolicy(
        chunk_points=20,
        max_retries=1,
        retry_backoff_seconds=0,
    )
    first = collect_historical_dataset(
        symbol="BTC/USDT",
        start=START,
        end=END,
        output_dir=tmp_path,
        dataset_version="1.0.0",
        provider=provider,
        policy=policy,
        code_revision="a" * 40,
        sleep_fn=lambda _: None,
    )
    assert provider.calls
    assert set(first.candles_by_timeframe) == {"15m", "1h", "4h", "1d"}

    second_provider = FakeGateProvider()
    second = collect_historical_dataset(
        symbol="BTC/USDT",
        start=START,
        end=END,
        output_dir=tmp_path,
        dataset_version="1.0.0",
        provider=second_provider,
        policy=policy,
        code_revision="a" * 40,
        sleep_fn=lambda _: None,
    )
    assert second_provider.calls == []
    assert (
        first.manifest["dataset_bundle_fingerprint"]
        == second.manifest["dataset_bundle_fingerprint"]
    )
    verified = load_locked_dataset(tmp_path)
    assert len(verified.candles_by_timeframe["15m"]) == 3 * 24 * 4


def test_backfill_retries_transient_provider_failure(tmp_path):
    provider = FakeGateProvider(failures_remaining=[1])
    sleeps: list[float] = []
    collect_historical_dataset(
        symbol="BTC/USDT",
        start=START,
        end=END,
        output_dir=tmp_path,
        dataset_version="1.0.0",
        provider=provider,
        policy=HistoricalBackfillPolicy(
            chunk_points=1000,
            max_retries=2,
            retry_backoff_seconds=0.25,
        ),
        sleep_fn=sleeps.append,
    )
    assert sleeps == [0.25]


def test_locked_dataset_detects_file_tampering(tmp_path):
    collect_historical_dataset(
        symbol="BTC/USDT",
        start=START,
        end=END,
        output_dir=tmp_path,
        dataset_version="1.0.0",
        provider=FakeGateProvider(),
        policy=HistoricalBackfillPolicy(
            chunk_points=1000,
            retry_backoff_seconds=0,
        ),
        sleep_fn=lambda _: None,
    )
    locked_file = tmp_path / "locked" / "btc-usdt" / "15m.jsonl"
    lines = locked_file.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row["close"] = "999999"
    lines[0] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    locked_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="file checksum mismatch"):
        load_locked_dataset(tmp_path)


def test_gate_range_uses_from_to_without_limit():
    client = RecordingHttpClient()
    provider = GateIOProvider(client=client)  # type: ignore[arg-type]
    rows = provider.get_candles_range(
        "BTC/USDT",
        "15m",
        START,
        START,
    )
    assert len(rows) == 1
    assert client.urls
    url = client.urls[0]
    assert "currency_pair=BTC_USDT" in url
    assert "interval=15m" in url
    assert f"from={int(START.timestamp())}" in url
    assert f"to={int(START.timestamp())}" in url
    assert "limit=" not in url


def test_gate_range_rejects_more_than_1000_theoretical_points():
    provider = GateIOProvider()
    with pytest.raises(ValueError, match="1000-point"):
        provider.get_candles_range(
            "BTC/USDT",
            "15m",
            START,
            START + timedelta(minutes=15 * 1000),
        )
