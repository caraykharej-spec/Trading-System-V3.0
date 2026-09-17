from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

from scripts.backtest.run_hf_qualified_asset_backtest import _json_ready, select_source_summary


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
