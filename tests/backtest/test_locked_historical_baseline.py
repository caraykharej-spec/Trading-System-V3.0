from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from app.backtest.locked_baseline_runner import run_locked_historical_baseline
from app.data.historical_backfill import LockedDatasetBundle
from app.data.market_data import Candle
from app.storm_costs import StormCostService, parse_market_cost_snapshot

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
EVALUATION_START = datetime(2026, 8, 25, 0, 0, tzinfo=timezone.utc)
MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}


class FakeCostService(StormCostService):
    def snapshot_for(self, symbol: str):  # type: ignore[no-untyped-def]
        return parse_market_cost_snapshot(
            {
                "address": "0:btc",
                "config": {
                    "ticker": symbol,
                    "type": "base",
                    "settlementToken": "USDT",
                },
                "settings": {
                    "fee": "1200000",
                    "executionFee": "200000",
                    "rolloverFee": "300000000",
                    "fundingPeriod": 3600,
                    "maxPriceImpact": "2400000",
                    "maxPriceSpread": "4800000",
                    "liquidationFeeRatio": "10000000",
                },
                "amm": {
                    "blockTimestamp": "2026-09-13T12:00:00Z",
                    "longFundingRate": "18000",
                    "shortFundingRate": "18000",
                    "vpiSpread": "150000",
                },
            }
        )


def _candles(timeframe: str, count: int = 220) -> list[Candle]:
    step = timedelta(minutes=MINUTES[timeframe])
    start = NOW - step * count
    rows: list[Candle] = []
    for index in range(count):
        price = Decimal("100") + Decimal(index) / Decimal("10")
        rows.append(
            Candle(
                "BTC/USDT",
                timeframe,
                start + step * index,
                price,
                price + Decimal("1"),
                price - Decimal("1"),
                price + Decimal("0.2"),
                Decimal("1000"),
            )
        )
    return rows


def _bundle(*, daily_count: int = 220) -> LockedDatasetBundle:
    manifest: dict[str, object] = {
        "provider": "gateio",
        "symbol": "BTC/USDT",
        "dataset_version": "1.0.0",
        "requested_start": "2025-02-01T00:00:00+00:00",
        "requested_end": "2026-09-13T00:00:00+00:00",
        "dataset_bundle_fingerprint": "a" * 64,
        "manifest_fingerprint": "b" * 64,
        "source_shards_fingerprint": "c" * 64,
        "code_revision": "d" * 40,
    }
    candles = {timeframe: _candles(timeframe) for timeframe in MINUTES}
    candles["1d"] = _candles("1d", daily_count)
    return LockedDatasetBundle(Path("/verified/locked"), manifest, candles)


def test_locked_baseline_preserves_dataset_identity_cost_and_warmup_evidence():
    with patch(
        "app.backtest.locked_baseline_runner.load_locked_dataset",
        return_value=_bundle(),
    ):
        report = run_locked_historical_baseline(
            "/verified/locked",
            evaluation_start=EVALUATION_START,
            cost_service=FakeCostService(),
            code_revision="e" * 40,
        )

    assert report["run_type"] == "LOCKED_HISTORICAL_BASELINE"
    assert report["mode"] == "RESEARCH_PAPER_ONLY"
    assert report["dataset_bundle_fingerprint"] == "a" * 64
    assert report["dataset_manifest_fingerprint"] == "b" * 64
    assert report["dataset_source_shards_fingerprint"] == "c" * 64
    assert report["dataset_code_revision"] == "d" * 40
    assert report["backtest_code_revision"] == "e" * 40
    assert report["evaluation_start"] == EVALUATION_START.isoformat()
    assert report["evaluation_end"] == "2026-09-13T00:00:00+00:00"
    assert report["warmup_required_daily_candles"] == 200
    assert report["warmup_completed_daily_candles"] >= 200
    assert len(str(report["evidence_fingerprint"])) == 64

    config = report["backtest_config"]
    assert isinstance(config, dict)
    assert config["commission_percent"] == "0.1200"
    assert config["spread_percent"] == "0.01500"
    assert config["slippage_percent"] == "0"
    assert config["funding_rate_percent_per_day"] == "0"

    costs = report["cost_evidence"]
    assert isinstance(costs, dict)
    assert "NOT_CALIBRATED" in str(costs["slippage_status"])
    assert "NO_HISTORICAL_FUNDING_BACKFILL" in str(costs["funding_status"])


def test_locked_baseline_evidence_seals_backtest_code_revision():
    bundle = _bundle()
    with patch(
        "app.backtest.locked_baseline_runner.load_locked_dataset",
        return_value=bundle,
    ):
        first = run_locked_historical_baseline(
            "/verified/locked",
            evaluation_start=EVALUATION_START,
            cost_service=FakeCostService(),
            code_revision="e" * 40,
        )
        second = run_locked_historical_baseline(
            "/verified/locked",
            evaluation_start=EVALUATION_START,
            cost_service=FakeCostService(),
            code_revision="f" * 40,
        )

    assert first["dataset_bundle_fingerprint"] == second["dataset_bundle_fingerprint"]
    assert first["evidence_fingerprint"] != second["evidence_fingerprint"]


def test_locked_baseline_fails_closed_without_200_completed_daily_warmup():
    bundle = _bundle(daily_count=199)
    with patch(
        "app.backtest.locked_baseline_runner.load_locked_dataset",
        return_value=bundle,
    ):
        with pytest.raises(ValueError, match="insufficient completed daily warm-up"):
            run_locked_historical_baseline(
                "/verified/locked",
                evaluation_start=EVALUATION_START,
                cost_service=FakeCostService(),
                code_revision="e" * 40,
            )


def test_locked_baseline_rejects_naive_evaluation_start():
    with patch(
        "app.backtest.locked_baseline_runner.load_locked_dataset",
        return_value=_bundle(),
    ):
        with pytest.raises(ValueError, match="timezone-aware"):
            run_locked_historical_baseline(
                "/verified/locked",
                evaluation_start=datetime(2026, 8, 25, 0, 0),
                cost_service=FakeCostService(),
                code_revision="e" * 40,
            )
