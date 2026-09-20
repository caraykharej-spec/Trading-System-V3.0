"""Execute leakage-safe Phase 48.2 Locked OOS + pre-OOS walk-forward research."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.backtest.baseline_runner import _cost_config, _fingerprint, _result_payload
from app.backtest.engine import BacktestEngine
from app.backtest.locked_oos import seal_oos_plan, validate_walk_forward_boundaries
from app.backtest.models import BacktestConfig, BacktestResult
from app.storm_costs import StormCostService
from app.strategy.rules import DEFAULT_RULES
from scripts.backtest.hf_qualified_data import (
    asset_execution_status,
    find_asset,
    load_candles,
    load_json,
    select_source_summary,
)


def _json_ready(value: Any) -> Any:
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


def _sha_payload(payload: object) -> str:
    encoded = json.dumps(_json_ready(payload), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _slice_to(candles: dict[str, list[Any]], end: datetime) -> dict[str, list[Any]]:
    return {
        timeframe: [row for row in rows if row.timestamp <= end]
        for timeframe, rows in candles.items()
    }


def _metrics(result: BacktestResult) -> dict[str, Any]:
    trade_count = len(result.trades)
    expectancy = (
        sum((trade.realized_pnl for trade in result.trades), Decimal("0")) / Decimal(trade_count)
        if trade_count
        else Decimal("0")
    )
    expectancy_percent = (
        expectancy / result.initial_equity * Decimal("100")
        if result.initial_equity
        else Decimal("0")
    )
    payload = _result_payload(result)
    payload["expectancy_pnl"] = expectancy
    payload["expectancy_percent_of_initial_equity"] = expectancy_percent
    return payload


def build_pre_oos_walk_forward_windows(
    *, validation_end: int, window_count: int = 3
) -> tuple[tuple[int, int, int, int], ...]:
    """Create expanding-train, non-overlapping test windows wholly before locked OOS."""
    if window_count < 1:
        raise ValueError("window_count must be positive")
    if validation_end < 10:
        raise ValueError("insufficient observations for walk-forward")
    test_size = max(1, validation_end // (window_count + 4))
    first_train_end = validation_end - window_count * test_size
    if first_train_end <= 0:
        raise ValueError("walk-forward training segment is empty")
    windows = tuple(
        (
            0,
            first_train_end + index * test_size,
            first_train_end + index * test_size,
            first_train_end + (index + 1) * test_size,
        )
        for index in range(window_count)
    )
    validate_walk_forward_boundaries(windows, total_observations=validation_end)
    if windows[-1][3] != validation_end:
        raise ValueError("walk-forward windows must terminate at validation boundary")
    return windows


def _run_evaluation(
    *,
    symbol: str,
    candles: dict[str, list[Any]],
    config: BacktestConfig,
    evaluation_start: datetime,
    evaluation_end: datetime,
) -> BacktestResult:
    segment = _slice_to(candles, evaluation_end)
    return BacktestEngine(config).run(symbol, segment, evaluation_start=evaluation_start)


def _warmup_pending_report(
    *,
    asset: dict[str, Any],
    qualification: dict[str, Any],
    qualification_key: str,
    code_revision: str,
) -> dict[str, Any]:
    report = {
        "schema": "phase-48-2-locked-oos-v1",
        "phase": "48.2",
        "mode": "RESEARCH_PAPER_ONLY",
        "execution_status": "WARMUP_PENDING",
        "base_asset": str(asset["base_asset"]).upper(),
        "symbol": str(asset["storm_canonical_symbol"]),
        "qualification_status": asset.get("qualification_status"),
        "strategy_warmup_status": asset.get("strategy_warmup_status"),
        "warmup_deficiencies": asset.get("warmup_deficiencies", []),
        "qualification_object_key": qualification_key,
        "qualification_fingerprint": _sha_payload(qualification),
        "code_revision": code_revision,
        "performance_evidence": None,
        "limitations": (
            "Listing-limited asset retained as non-performance evidence until real warm-up history exists.",
            "No synthetic, forward-filled, pre-listing, or zero-return performance is introduced.",
        ),
    }
    report["evidence_fingerprint"] = _fingerprint(report)
    return report


def run_asset(
    *,
    base_asset: str,
    qualification_key: str,
    code_revision: str,
    walk_forward_windows: int = 3,
) -> dict[str, Any]:
    qualification = load_json(qualification_key)
    asset = find_asset(qualification, base_asset)
    if asset_execution_status(asset) == "WARMUP_PENDING":
        return _warmup_pending_report(
            asset=asset,
            qualification=qualification,
            qualification_key=qualification_key,
            code_revision=code_revision,
        )

    manifest_keys = qualification.get("source_manifest_keys")
    if not isinstance(manifest_keys, list) or not manifest_keys:
        raise ValueError("qualification contract has no source manifests")
    manifests = [load_json(str(key)) for key in manifest_keys]
    summary = select_source_summary(asset, manifests)
    symbol = str(asset["storm_canonical_symbol"])
    candles, partition_evidence = load_candles(summary, symbol)

    config, cost_evidence = _cost_config(StormCostService(), symbol)
    strategy_payload = asdict(DEFAULT_RULES)
    config_payload = asdict(config)
    qualification_fingerprint = _sha_payload(qualification)
    partition_fingerprint_input = [
        {
            "object_key": row["object_key"],
            "sha256": row["sha256"],
            "timeframe": row["timeframe"],
        }
        for row in sorted(
            partition_evidence,
            key=lambda item: (item["timeframe"], item["object_key"]),
        )
    ]
    dataset_fingerprint = _sha_payload(
        {
            "qualification": qualification_fingerprint,
            "partitions": partition_fingerprint_input,
        }
    )
    strategy_fingerprint = _fingerprint(strategy_payload)
    config_fingerprint = _fingerprint(config_payload)

    fifteen = sorted(candles["15m"], key=lambda row: row.timestamp)
    plan = seal_oos_plan(
        dataset_sha256=dataset_fingerprint,
        strategy_fingerprint=strategy_fingerprint,
        config_fingerprint=config_fingerprint,
        total_observations=len(fifteen),
    )
    plan.verify(
        dataset_sha256=dataset_fingerprint,
        strategy_fingerprint=strategy_fingerprint,
        config_fingerprint=config_fingerprint,
    )

    train_start = fifteen[0].timestamp
    train_end = fifteen[plan.train_end - 1].timestamp
    validation_start = fifteen[plan.train_end].timestamp
    validation_end = fifteen[plan.validation_end - 1].timestamp
    oos_start = fifteen[plan.validation_end].timestamp
    oos_end = fifteen[-1].timestamp

    train_result = _run_evaluation(
        symbol=symbol,
        candles=candles,
        config=config,
        evaluation_start=train_start,
        evaluation_end=train_end,
    )
    validation_result = _run_evaluation(
        symbol=symbol,
        candles=candles,
        config=config,
        evaluation_start=validation_start,
        evaluation_end=validation_end,
    )

    wf_boundaries = build_pre_oos_walk_forward_windows(
        validation_end=plan.validation_end,
        window_count=walk_forward_windows,
    )
    wf_results: list[dict[str, Any]] = []
    for index, (
        wf_train_start,
        wf_train_end,
        wf_test_start,
        wf_test_end,
    ) in enumerate(wf_boundaries, start=1):
        test_start = fifteen[wf_test_start].timestamp
        test_end = fifteen[wf_test_end - 1].timestamp
        result = _run_evaluation(
            symbol=symbol,
            candles=candles,
            config=config,
            evaluation_start=test_start,
            evaluation_end=test_end,
        )
        wf_results.append(
            {
                "window": index,
                "train_indices": [wf_train_start, wf_train_end],
                "test_indices": [wf_test_start, wf_test_end],
                "test_start": test_start,
                "test_end": test_end,
                "selection_policy": "FROZEN_STRATEGY_AND_CONFIG_NO_OOS_TUNING",
                "metrics": _metrics(result),
            }
        )

    # Locked OOS is evaluated exactly once after fingerprints, split and pre-OOS evidence are sealed.
    oos_result = _run_evaluation(
        symbol=symbol,
        candles=candles,
        config=config,
        evaluation_start=oos_start,
        evaluation_end=oos_end,
    )

    report: dict[str, Any] = {
        "schema": "phase-48-2-locked-oos-v1",
        "phase": "48.2",
        "mode": "RESEARCH_PAPER_ONLY",
        "execution_status": "COMPLETE",
        "base_asset": base_asset.upper(),
        "symbol": symbol,
        "qualification_status": asset.get("qualification_status"),
        "qualification_object_key": qualification_key,
        "qualification_fingerprint": qualification_fingerprint,
        "qualification_generated_at": qualification.get("generated_at"),
        "source_manifest_keys": manifest_keys,
        "dataset_fingerprint": dataset_fingerprint,
        "strategy_fingerprint": strategy_fingerprint,
        "config_fingerprint": config_fingerprint,
        "code_revision": code_revision,
        "split": {
            "policy": "60_TRAIN_20_VALIDATION_20_LOCKED_OOS_CHRONOLOGICAL",
            "total_15m_observations": len(fifteen),
            "train_indices": [0, plan.train_end],
            "validation_indices": [plan.train_end, plan.validation_end],
            "oos_indices": [plan.validation_end, plan.oos_end],
            "train_start": train_start,
            "train_end": train_end,
            "validation_start": validation_start,
            "validation_end": validation_end,
            "oos_start": oos_start,
            "oos_end": oos_end,
            "sealed_at": plan.sealed_at,
            "plan_sha256": plan.plan_sha256,
        },
        "partition_evidence": partition_evidence,
        "candle_counts": {key: len(value) for key, value in candles.items()},
        "strategy_rules": strategy_payload,
        "backtest_config": config_payload,
        "cost_evidence": cost_evidence,
        "train_metrics": _metrics(train_result),
        "validation_metrics": _metrics(validation_result),
        "walk_forward": {
            "scope": "PRE_OOS_ONLY",
            "window_count": len(wf_results),
            "windows": wf_results,
        },
        "locked_oos_metrics": _metrics(oos_result),
        "leakage_controls": (
            "Chronological split is sealed before locked OOS execution.",
            "Walk-forward test windows terminate at the validation boundary and cannot touch locked OOS.",
            "Strategy and backtest config fingerprints are frozen for this Phase 48.2 runner; no OOS tuning is permitted.",
            "Each evaluation segment is truncated at its own end timestamp; later candles are unavailable to BacktestEngine.",
        ),
        "limitations": (
            "This phase qualifies temporal generalization, not live trading authorization.",
            "Historical funding, calibrated slippage and market impact remain Phase 48.8 stress dimensions.",
        ),
    }
    report["evidence_fingerprint"] = _fingerprint(report)
    return _json_ready(report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-asset", required=True)
    parser.add_argument(
        "--qualification-key",
        default="manifests/global-history/v1/latest.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--git-revision",
        default=os.environ.get("GITHUB_SHA", "UNKNOWN"),
    )
    parser.add_argument("--walk-forward-windows", type=int, default=3)
    args = parser.parse_args()
    report = run_asset(
        base_asset=args.base_asset,
        qualification_key=args.qualification_key,
        code_revision=args.git_revision,
        walk_forward_windows=args.walk_forward_windows,
    )
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_json_dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "base_asset": report["base_asset"],
                "status": report["execution_status"],
                "evidence_fingerprint": report["evidence_fingerprint"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
