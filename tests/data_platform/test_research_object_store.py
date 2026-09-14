from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.data.historical_backfill import HistoricalBackfillPolicy, collect_historical_dataset
from app.data.market_data import Candle
from app.data.providers.gateio import GateIOProvider
from app.data.quality import timeframe_seconds
from app.data.research_object_store import (
    ResearchStoreError,
    build_research_bundle,
    verify_research_bundle,
)

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_END = datetime(2026, 1, 3, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FakeGateProvider(GateIOProvider):
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
        while cursor <= end:
            base = Decimal("100") + Decimal(str(int(cursor.timestamp()) % 1000)) / Decimal("1000")
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


def _locked_dataset(tmp_path):  # type: ignore[no-untyped-def]
    root = tmp_path / "locked-source"
    return collect_historical_dataset(
        symbol="BTC/USDT",
        start=_START,
        end=_END,
        output_dir=root,
        dataset_version="1.0.0",
        provider=FakeGateProvider(),
        policy=HistoricalBackfillPolicy(
            chunk_points=1000,
            max_retries=0,
            retry_backoff_seconds=0,
        ),
        code_revision="a" * 40,
        sleep_fn=lambda _: None,
    )


def test_build_and_verify_parquet_research_bundle(tmp_path):
    source = _locked_dataset(tmp_path)
    output = tmp_path / "research-bundle"

    built = build_research_bundle(
        source.root,
        output,
        git_revision="b" * 40,
    )
    verified = verify_research_bundle(output)

    assert built.dataset_fingerprint == verified.dataset_fingerprint
    assert verified.manifest["storage_format"] == "parquet"
    assert verified.manifest["compression"] == "zstd"
    assert verified.manifest["qualification_status"] == "RESEARCH_PAPER_ONLY"
    assert verified.object_prefix.startswith("gold/locked-research-datasets/v1/btc-usdt/")
    assert (output / "manifest.json").is_file()
    assert (output / "checksums.json").is_file()
    for timeframe in ("15m", "1h", "4h", "1d"):
        assert (output / "parquet" / f"{timeframe}.parquet").is_file()


def test_research_bundle_detects_parquet_tampering(tmp_path):
    source = _locked_dataset(tmp_path)
    output = tmp_path / "research-bundle"
    build_research_bundle(source.root, output, git_revision="c" * 40)

    parquet = output / "parquet" / "15m.parquet"
    parquet.write_bytes(parquet.read_bytes() + b"tamper")

    with pytest.raises(ResearchStoreError, match="checksum mismatch"):
        verify_research_bundle(output)


def test_research_bundle_detects_manifest_tampering(tmp_path):
    source = _locked_dataset(tmp_path)
    output = tmp_path / "research-bundle"
    build_research_bundle(source.root, output, git_revision="d" * 40)

    manifest = output / "manifest.json"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace("RESEARCH_PAPER_ONLY", "QUALIFIED"), encoding="utf-8")

    with pytest.raises(ResearchStoreError, match="manifest fingerprint mismatch"):
        verify_research_bundle(output)
