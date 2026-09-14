from __future__ import annotations

import csv
import gzip
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.data.gateio_deals_archive import (
    GateDealsArchivePolicy,
    collect_gate_deals_archive_dataset,
)
from app.data.providers.http import ProviderError

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 3, tzinfo=timezone.utc)


def _write_archive(path, *, missing_index: int | None = None, duplicate_id: bool = False):  # type: ignore[no-untyped-def]
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        count = int((END - START).total_seconds() // 300)
        for index in range(count):
            if index == missing_index:
                continue
            timestamp = START + timedelta(minutes=5 * index)
            deal_id = 1000 if duplicate_id and index == 1 else 1000 + index
            price = Decimal("100") + Decimal(index) / Decimal("100")
            amount = Decimal("0.5")
            writer.writerow(
                [
                    str(timestamp.timestamp()),
                    str(deal_id),
                    str(price),
                    str(amount),
                    "1" if index % 2 == 0 else "2",
                ]
            )


def test_deals_archive_reconstructs_and_locks_all_required_timeframes(tmp_path):
    def downloader(url, destination):  # type: ignore[no-untyped-def]
        assert url.endswith("/spot/deals/202601/BTC_USDT-202601.csv.gz")
        _write_archive(destination)

    bundle = collect_gate_deals_archive_dataset(
        symbol="BTC/USDT",
        archive_month="202601",
        start=START,
        end=END,
        output_dir=tmp_path,
        dataset_version="1.0.0",
        policy=GateDealsArchivePolicy(max_retries=0, retry_backoff_seconds=0),
        code_revision="a" * 40,
        sleep_fn=lambda _: None,
        downloader=downloader,
    )

    assert bundle.manifest["provider"] == "gateio"
    assert bundle.manifest["requested_start"] == START.isoformat()
    assert bundle.manifest["requested_end"] == END.isoformat()
    assert len(bundle.candles_by_timeframe["15m"]) == 2 * 24 * 4
    assert len(bundle.candles_by_timeframe["1h"]) == 2 * 24
    assert len(bundle.candles_by_timeframe["4h"]) == 2 * 6
    assert len(bundle.candles_by_timeframe["1d"]) == 2
    assert not (tmp_path / ".work").exists()

    first = bundle.candles_by_timeframe["15m"][0]
    expected_volume = sum(
        (
            (Decimal("100") + Decimal(index) / Decimal("100")) * Decimal("0.5")
            for index in range(3)
        ),
        Decimal("0"),
    )
    assert first.open == Decimal("100")
    assert first.close == Decimal("100.02")
    assert first.volume == expected_volume

    source = bundle.manifest["archive_source"]
    assert isinstance(source, dict)
    assert source["source_kind"] == "gateio_spot_deals_archive"
    assert source["archive_month"] == "202601"
    assert source["base_5m_candle_count"] == 2 * 24 * 12
    assert source["in_range_trade_rows"] == 2 * 24 * 12
    assert source["candle_volume_semantics"] == "quote_currency=sum(price*base_amount)"
    assert len(str(source["compressed_sha256"])) == 64


def test_deals_archive_fails_closed_on_missing_five_minute_bucket(tmp_path):
    def downloader(url, destination):  # type: ignore[no-untyped-def]
        _write_archive(destination, missing_index=17)

    with pytest.raises(ProviderError, match="missing 1 5m bucket"):
        collect_gate_deals_archive_dataset(
            symbol="BTC/USDT",
            archive_month="202601",
            start=START,
            end=END,
            output_dir=tmp_path,
            dataset_version="1.0.0",
            policy=GateDealsArchivePolicy(max_retries=0, retry_backoff_seconds=0),
            sleep_fn=lambda _: None,
            downloader=downloader,
        )


def test_deals_archive_fails_closed_on_duplicate_deal_id(tmp_path):
    def downloader(url, destination):  # type: ignore[no-untyped-def]
        _write_archive(destination, duplicate_id=True)

    with pytest.raises(ProviderError, match="duplicate Gate deal id"):
        collect_gate_deals_archive_dataset(
            symbol="BTC/USDT",
            archive_month="202601",
            start=START,
            end=END,
            output_dir=tmp_path,
            dataset_version="1.0.0",
            policy=GateDealsArchivePolicy(max_retries=0, retry_backoff_seconds=0),
            sleep_fn=lambda _: None,
            downloader=downloader,
        )


def test_deals_archive_retries_provider_failure(tmp_path):
    attempts = [0]
    sleeps: list[float] = []

    def downloader(url, destination):  # type: ignore[no-untyped-def]
        attempts[0] += 1
        if attempts[0] == 1:
            raise ProviderError("transient")
        _write_archive(destination)

    collect_gate_deals_archive_dataset(
        symbol="BTC/USDT",
        archive_month="202601",
        start=START,
        end=END,
        output_dir=tmp_path,
        dataset_version="1.0.0",
        policy=GateDealsArchivePolicy(max_retries=1, retry_backoff_seconds=0.25),
        sleep_fn=sleeps.append,
        downloader=downloader,
    )

    assert attempts == [2]
    assert sleeps == [0.25]
