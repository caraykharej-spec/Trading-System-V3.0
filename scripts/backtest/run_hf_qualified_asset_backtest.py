"""Run one fail-closed backtest from the qualified HF historical-data contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import pyarrow.parquet as pq

from app.backtest.baseline_runner import _cost_config, _fingerprint, _result_payload
from app.backtest.engine import BacktestEngine
from app.data.market_data import Candle
from app.storm_costs import StormCostService
from scripts.backtest import hf_s3

_REQUIRED_TIMEFRAMES = ("15m", "1h", "4h", "1d")
_COMPLETE_GATE = {"COMPLETE", "COMPLETE_WITH_RECORDED_GAPS"}


def _bucket() -> str:
    value = os.environ.get("HF_S3_BUCKET", "").strip()
    if not value:
        raise RuntimeError("HF_S3_BUCKET is required")
    return value


def _json_ready(value: Any) -> Any:
    """Convert report values to deterministic JSON-compatible primitives."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _json_dumps(payload: object, *, indent: int | None = None) -> str:
    return json.dumps(_json_ready(payload), indent=indent, sort_keys=True)


def _download(key: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    hf_s3.aws(
        "s3api", "get-object", "--bucket", _bucket(), "--key", key, str(target)
    )


def _load_json(key: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="hf-backtest-json-") as temp_dir:
        target = Path(temp_dir) / "payload.json"
        _download(key, target)
        payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"HF object is not a JSON object: {key}")
    return payload


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
            if provider.startswith("gateio") and status not in _COMPLETE_GATE:
                continue
            if provider == "yahoo" and status != "COMPLETE":
                continue
            selected = summary
    if selected is None:
        base = qualification_asset.get("base_asset")
        raise ValueError(
            f"qualified source evidence not found for {base}: {provider}:{provider_symbol}"
        )
    return selected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_candles(
    summary: dict[str, Any], canonical_symbol: str
) -> tuple[dict[str, list[Candle]], list[dict[str, Any]]]:
    raw_partitions = summary.get("partitions")
    if not isinstance(raw_partitions, list):
        raise ValueError("qualified source summary is missing partitions")
    candles: dict[str, dict[datetime, Candle]] = {
        timeframe: {} for timeframe in _REQUIRED_TIMEFRAMES
    }
    evidence: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="hf-qualified-backtest-") as temp_dir:
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
            _download(key, target)
            actual_sha = _sha256(target)
            expected_sha = str(partition.get("sha256") or "")
            verified = len(expected_sha) == 64 and actual_sha == expected_sha.lower()
            if len(expected_sha) == 64 and not verified:
                raise ValueError(f"partition SHA-256 mismatch: {key}")
            table = pq.read_table(
                target,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            rows = table.to_pylist()
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
        if len(rows) < 200:
            raise ValueError(f"insufficient {timeframe} rows after download: {len(rows)}")
    return output, evidence


def run_asset(
    *, base_asset: str, qualification_key: str, code_revision: str
) -> dict[str, Any]:
    qualification = _load_json(qualification_key)
    if qualification.get("status") != "PASS_GLOBAL_HISTORY_QUALIFICATION":
        raise ValueError("global historical qualification is not PASS")
    if qualification.get("storm_asset_count") != 81:
        raise ValueError("qualified universe is not the locked 81-asset scope")
    assets = qualification.get("assets")
    if not isinstance(assets, list):
        raise ValueError("qualification contract is missing assets")
    asset = next(
        (
            item
            for item in assets
            if isinstance(item, dict)
            and str(item.get("base_asset") or "").upper() == base_asset.upper()
        ),
        None,
    )
    if asset is None or asset.get("qualification_status") != "QUALIFIED":
        raise ValueError(f"asset is not qualified: {base_asset}")
    manifest_keys = qualification.get("source_manifest_keys")
    if not isinstance(manifest_keys, list) or not manifest_keys:
        raise ValueError("qualification contract has no source manifests")
    manifests = [_load_json(str(key)) for key in manifest_keys]
    summary = select_source_summary(asset, manifests)
    canonical = str(asset["storm_canonical_symbol"])
    candles, partition_evidence = load_candles(summary, canonical)
    config, cost_evidence = _cost_config(StormCostService(), canonical)
    result = BacktestEngine(config).run(canonical, candles)
    report: dict[str, Any] = {
        "schema": "hf-qualified-asset-backtest-v1",
        "run_type": "GLOBAL_81_ASSET_HF_QUALIFIED_BACKTEST",
        "mode": "RESEARCH_PAPER_ONLY",
        "base_asset": base_asset.upper(),
        "symbol": canonical,
        "qualification_object_key": qualification_key,
        "qualification_generated_at": qualification.get("generated_at"),
        "qualification_source_manifest_keys": manifest_keys,
        "source": asset["historical_source"],
        "coverage": asset["coverage"],
        "partition_evidence": partition_evidence,
        "candle_counts": {key: len(value) for key, value in candles.items()},
        "cost_evidence": cost_evidence,
        "code_revision": code_revision,
        "result": _result_payload(result),
        "limitations": (
            "Independent per-asset research backtest; results are not portfolio aggregation.",
            "Current Storm fee/spread snapshot is used; historical funding, calibrated slippage, and market impact remain Phase 48.8 stress dimensions.",
            "A successful run does not authorize live trading or imply future profitability.",
        ),
    }
    report["evidence_fingerprint"] = _fingerprint(_json_ready(report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-asset", required=True)
    parser.add_argument(
        "--qualification-key", default="manifests/global-history/v1/latest.json"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--git-revision", default=os.environ.get("GITHUB_SHA", "UNKNOWN"))
    args = parser.parse_args()
    report = run_asset(
        base_asset=args.base_asset,
        qualification_key=args.qualification_key,
        code_revision=args.git_revision,
    )
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        _json_dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "base_asset": report["base_asset"],
                "symbol": report["symbol"],
                "status": "COMPLETE",
                "evidence_fingerprint": report["evidence_fingerprint"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
