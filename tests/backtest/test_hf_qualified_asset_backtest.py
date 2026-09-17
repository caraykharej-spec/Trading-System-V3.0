from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.backtest.aggregate_hf_global_backtest import aggregate
from scripts.backtest.run_hf_qualified_asset_backtest import (
    _asset_execution_status,
    _json_ready,
    select_source_summary,
)


def test_json_ready_serializes_decimal_datetime_and_date() -> None:
    payload = _json_ready(
        {
            "decimal": Decimal("1.2300"),
            "datetime": datetime(2026, 9, 17, 12, 30, tzinfo=timezone.utc),
            "date": date(2026, 9, 17),
        }
    )
    assert payload == {
        "decimal": "1.2300",
        "datetime": "2026-09-17T12:30:00+00:00",
        "date": "2026-09-17",
    }
    json.dumps(payload, sort_keys=True)


def test_later_repair_manifest_overrides_older_route_summary() -> None:
    asset = {
        "base_asset": "TON",
        "historical_source": {
            "provider": "gateio",
            "provider_symbol": "GRAM_USDT",
            "price_multiplier": "1",
        },
    }
    old = {
        "route_summaries": [
            {
                "status": "COMPLETE",
                "route": {
                    "provider": "gateio",
                    "provider_symbol": "GRAM_USDT",
                    "price_multiplier": "1",
                },
                "partitions": [{"object_key": "old"}],
            }
        ]
    }
    repair = {
        "route_summaries": [
            {
                "status": "COMPLETE_WITH_RECORDED_GAPS",
                "route": {
                    "provider": "gateio",
                    "provider_symbol": "GRAM_USDT",
                    "price_multiplier": "1",
                },
                "partitions": [{"object_key": "repair"}],
            }
        ]
    }

    selected = select_source_summary(asset, [old, repair])

    assert selected["partitions"][0]["object_key"] == "repair"


def test_yahoo_manifest_without_provider_field_is_supported() -> None:
    asset = {
        "base_asset": "SPX",
        "historical_source": {
            "provider": "yahoo",
            "provider_symbol": "^GSPC",
            "price_multiplier": "1",
        },
    }
    manifest = {
        "route_summaries": [
            {
                "status": "COMPLETE",
                "route": {
                    "provider_symbol": "^GSPC",
                    "price_multiplier": "1",
                },
                "partitions": [],
            }
        ]
    }

    assert select_source_summary(asset, [manifest]) is manifest["route_summaries"][0]


def test_listing_limited_asset_with_pending_warmup_is_not_rejected() -> None:
    asset = {
        "base_asset": "SPCX",
        "qualification_status": "QUALIFIED_LISTING_LIMITED_HISTORY",
        "strategy_warmup_status": "PENDING_MINIMUM_CANDLES",
    }

    assert _asset_execution_status(asset) == "WARMUP_PENDING"


def test_unqualified_asset_remains_fail_closed() -> None:
    asset = {
        "base_asset": "BAD",
        "qualification_status": "INSUFFICIENT_BACKTEST_HISTORY",
    }

    with pytest.raises(ValueError, match="asset is not qualified"):
        _asset_execution_status(asset)


def test_aggregate_excludes_warmup_pending_assets_from_performance_metrics(
    tmp_path: Path,
) -> None:
    pending = {"SKY", "SPCX"}
    paths: list[Path] = []
    for index in range(81):
        base_asset = "SKY" if index == 79 else "SPCX" if index == 80 else f"A{index:02d}"
        path = tmp_path / f"{index:02d}.json"
        if base_asset in pending:
            payload = {
                "base_asset": base_asset,
                "symbol": f"{base_asset}/USDT",
                "execution_status": "WARMUP_PENDING",
                "qualification_status": "QUALIFIED_LISTING_LIMITED_HISTORY",
                "strategy_warmup_status": "PENDING_MINIMUM_CANDLES",
                "warmup_deficiencies": [{"timeframe": "1d"}],
                "evidence_fingerprint": f"pending-{base_asset}",
                "result": None,
            }
        else:
            payload = {
                "base_asset": base_asset,
                "symbol": f"{base_asset}/USDT",
                "execution_status": "COMPLETE",
                "evidence_fingerprint": f"complete-{base_asset}",
                "result": {
                    "trade_count": 1,
                    "total_return_percent": "1",
                    "max_drawdown_percent": "2",
                },
            }
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)

    result = aggregate(paths)

    assert result["status"] == "PASS_QUALIFIED_UNIVERSE_WITH_WARMUP_PENDING"
    assert result["qualified_universe_asset_count"] == 81
    assert result["backtested_asset_count"] == 79
    assert result["warmup_pending_asset_count"] == 2
    assert result["warmup_pending_assets"] == ["SKY", "SPCX"]
    assert result["total_trade_count"] == 79
    assert result["positive_return_asset_count"] == 79
    assert result["zero_return_asset_count"] == 0
