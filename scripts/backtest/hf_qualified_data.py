"""Shared loaders for fail-closed HF-qualified research backtests."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import pyarrow.parquet as pq

from app.data.market_data import Candle
from scripts.backtest import hf_s3

REQUIRED_TIMEFRAMES = ("15m", "1h", "4h", "1d")
COMPLETE_GATE = {"COMPLETE", "COMPLETE_WITH_RECORDED_GAPS"}
COMPLETE_RESEARCH_PROVIDERS = {"yahoo", "alpaca_sip", "dukascopy"}
QUALIFIED_STATUSES = {"QUALIFIED", "QUALIFIED_LISTING_LIMITED_HISTORY"}


def bucket() -> str:
    value = os.environ.get("HF_S3_BUCKET", "").strip()
    if not value:
        raise RuntimeError("HF_S3_BUCKET is required")
    return value


def download(key: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    hf_s3.aws("s3api", "get-object", "--bucket", bucket(), "--key", key, str(target))


def load_json(key: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="hf-qualified-json-") as temp_dir:
        target = Path(temp_dir) / "payload.json"
        download(key, target)
        payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"HF object is not a JSON object: {key}")
    return payload


def asset_execution_status(asset: dict[str, Any]) -> str:
    qualification_status = str(asset.get("qualification_status") or "")
    if qualification_status not in QUALIFIED_STATUSES:
        raise ValueError(f"asset is not qualified: {asset.get('base_asset', 'UNKNOWN')}")
    warmup_status = str(asset.get("strategy_warmup_status") or "READY")
    if qualification_status == "QUALIFIED_LISTING_LIMITED_HISTORY":
        if warmup_status == "PENDING_MINIMUM_CANDLES":
            return "WARMUP_PENDING"
        if warmup_status != "READY":
            raise ValueError(f"unsupported strategy warm-up status: {warmup_status}")
    return "COMPLETE"


def find_asset(qualification: dict[str, Any], base_asset: str) -> dict[str, Any]:
    if qualification.get("status") != "PASS_GLOBAL_HISTORY_QUALIFICATION":
        raise ValueError("global historical qualification is not PASS")
    if qualification.get("storm_asset_count") != 81 or qualification.get("qualified_asset_count") != 81:
        raise ValueError("qualification is not the locked 81/81 universe")
    assets = qualification.get("assets")
    if not isinstance(assets, list):
        raise ValueError("qualification contract is missing assets")
    selected = next(
        (item for item in assets if isinstance(item, dict) and str(item.get("base_asset") or "").upper() == base_asset.upper()),
        None,
    )
    if selected is None:
        raise ValueError(f"asset is not qualified: {base_asset}")
    return selected


def _route(summary: dict[str, Any]) -> dict[str, Any]:
    value = summary.get("route")
    return value if isinstance(value, dict) else {}


def _route_summaries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("route_summaries")
    if not isinstance(raw, list):
        raise ValueError("source run manifest is missing route_summaries")
    return [item for item in raw if isinstance(item, dict)]


def _decimal_equal(left: object, right: object) -> bool:
    try:
        return Decimal(str(left if left is not None else "1")) == Decimal(str(right))
    except Exception:
        return False


def select_source_summary(
    qualification_asset: dict[str, Any], manifests: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    source = qualification_asset.get("historical_source")
    if not isinstance(source, dict):
        raise ValueError("qualification asset is missing historical_source")
    provider = str(source.get("provider") or "").lower()
    provider_symbol = str(source.get("provider_symbol") or "").upper()
    multiplier = source.get("price_multiplier", "1")
    selected: dict[str, Any] | None = None
    for manifest in manifests:
        for summary in _route_summaries(manifest):
            route = _route(summary)
            actual_provider = str(route.get("provider") or "yahoo").lower()
            if actual_provider != provider:
                continue
            if str(route.get("provider_symbol") or "").upper() != provider_symbol:
                continue
            if not _decimal_equal(route.get("price_multiplier", "1"), multiplier):
                continue
            status = str(summary.get("status") or "")
            if provider.startswith("gateio") and status not in COMPLETE_GATE:
                continue
            if provider in COMPLETE_RESEARCH_PROVIDERS and status != "COMPLETE":
                continue
            selected = summary
    if selected is None:
        raise ValueError(
            f"qualified source evidence not found for {qualification_asset.get('base_asset')}: {provider}:{provider_symbol}"
        )
    return selected


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_candles(
    summary: dict[str, Any], canonical_symbol: str, *, minimum_rows: int = 200
) -> tuple[dict[str, list[Candle]], list[dict[str, Any]]]:
    raw_partitions = summary.get("partitions")
    if not isinstance(raw_partitions, list):
        raise ValueError("qualified source summary is missing partitions")
    candles: dict[str, dict[datetime, Candle]] = {timeframe: {} for timeframe in REQUIRED_TIMEFRAMES}
    evidence: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="hf-qualified-candles-") as temp_dir:
        root = Path(temp_dir)
        for index, partition in enumerate(raw_partitions):
            if not isinstance(partition, dict):
                continue
            timeframe = str(partition.get("timeframe") or "")
            if timeframe not in candles:
                continue
            key = str(partition.get("object_key") or "")
            if not key:
                raise ValueError(f"partition {index} is missing object_key")
            target = root / f"{index:05d}.parquet"
            download(key, target)
            actual_sha = sha256_file(target)
            expected_sha = str(partition.get("sha256") or "").lower()
            verified = len(expected_sha) == 64 and actual_sha == expected_sha
            if len(expected_sha) == 64 and not verified:
                raise ValueError(f"partition SHA-256 mismatch: {key}")
            rows = pq.read_table(
                target, columns=["timestamp", "open", "high", "low", "close", "volume"]
            ).to_pylist()
            for row in rows:
                timestamp = row["timestamp"]
                if not isinstance(timestamp, datetime):
                    timestamp = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError(f"partition has naive timestamp: {key}")
                timestamp = timestamp.astimezone(timezone.utc)
                volume = row.get("volume")
                candle = Candle(
                    symbol=canonical_symbol,
                    timeframe=timeframe,
                    timestamp=timestamp,
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    volume=Decimal(str(volume)) if volume not in (None, "") else Decimal("0"),
                )
                prior = candles[timeframe].get(timestamp)
                if prior is not None and prior != candle:
                    raise ValueError(f"conflicting duplicate candle: {timeframe} {timestamp}")
                candles[timeframe][timestamp] = candle
            evidence.append(
                {
                    "object_key": key,
                    "timeframe": timeframe,
                    "rows_read": len(rows),
                    "sha256": actual_sha,
                    "manifest_sha256": expected_sha or None,
                    "manifest_sha256_verified": verified,
                }
            )
    output = {
        timeframe: [mapping[key] for key in sorted(mapping)]
        for timeframe, mapping in candles.items()
    }
    for timeframe, rows in output.items():
        if len(rows) < minimum_rows:
            raise ValueError(f"insufficient {timeframe} rows after download: {len(rows)}")
    return output, evidence
