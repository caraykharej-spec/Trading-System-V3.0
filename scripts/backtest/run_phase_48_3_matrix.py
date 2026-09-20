"""Plan, execute, resume, and aggregate the real Phase 48.3 matrix.

Phase 48.3 consumes one immutable Phase 48.2 full-summary artifact.  The
1,000 experiment identities are sealed before execution, work is partitioned
by asset so HF candles are downloaded once per asset per attempt, and every
attempt (including failures) remains auditable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from app.backtest.baseline_runner import _fingerprint
from app.backtest.engine import BacktestEngine
from app.backtest.models import BacktestConfig
from app.backtest.qualification_matrix import MatrixDimensions, build_matrix
from scripts.backtest.hf_qualified_data import (
    find_asset,
    load_candles,
    load_json,
    select_source_summary,
)
from scripts.backtest.run_phase_48_2_locked_oos import (
    _json_ready,
    _metrics,
    _sha_payload,
    _slice_to,
)

MATRIX_RUN_COUNT = 1000
MATRIX_SEEDS = 500
SMOKE_RUN_COUNT = 10
SOURCE_SCHEMA = "phase-48-2-locked-oos-summary-v1"
PLAN_SCHEMA = "phase-48-3-real-matrix-plan-v1"
ATTEMPT_SCHEMA = "phase-48-3-real-matrix-attempt-v1"
SUMMARY_SCHEMA = "phase-48-3-real-matrix-summary-v1"


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        _json_ready(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _sha(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def verify_phase_48_2_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    if summary.get("schema") != SOURCE_SCHEMA:
        raise ValueError("unsupported Phase 48.2 summary schema")
    if summary.get("status") != "PASS_EXECUTION_EVIDENCE":
        raise ValueError("Phase 48.2 source evidence is not PASS")
    if summary.get("asset_report_count") != 81:
        raise ValueError("Phase 48.2 source does not contain the locked 81-asset universe")
    if summary.get("executed_asset_count") != 79:
        raise ValueError("Phase 48.2 source must contain exactly 79 executed assets")
    if summary.get("warmup_pending_asset_count") != 2:
        raise ValueError("Phase 48.2 source must contain exactly two pending assets")
    if sorted(summary.get("warmup_pending_assets") or []) != ["SKY", "SPCX"]:
        raise ValueError("Phase 48.2 pending assets must be SKY and SPCX")

    claimed = str(summary.get("evidence_fingerprint") or "")
    unsigned = dict(summary)
    unsigned.pop("evidence_fingerprint", None)
    if len(claimed) != 64 or _sha(unsigned) != claimed:
        raise ValueError("Phase 48.2 evidence fingerprint is invalid")

    raw_assets = summary.get("assets")
    if not isinstance(raw_assets, list):
        raise ValueError("Phase 48.2 summary is missing asset reports")
    complete = sorted(
        (
            item
            for item in raw_assets
            if isinstance(item, dict) and item.get("execution_status") == "COMPLETE"
        ),
        key=lambda item: str(item.get("base_asset") or ""),
    )
    if len(complete) != 79:
        raise ValueError("Phase 48.2 complete asset report count is inconsistent")
    bases = [str(item.get("base_asset") or "").upper() for item in complete]
    if not all(bases) or len(set(bases)) != 79:
        raise ValueError("Phase 48.2 complete asset identities are invalid")
    required = (
        "dataset_fingerprint",
        "strategy_fingerprint",
        "config_fingerprint",
        "qualification_fingerprint",
        "evidence_fingerprint",
    )
    for item in complete:
        if any(len(str(item.get(key) or "")) != 64 for key in required):
            raise ValueError(f"asset fingerprint missing: {item.get('base_asset')}")
    if len({str(item["strategy_fingerprint"]) for item in complete}) != 1:
        raise ValueError("Phase 48.2 assets do not share one frozen strategy fingerprint")
    if len({str(item["qualification_fingerprint"]) for item in complete}) != 1:
        raise ValueError("Phase 48.2 assets do not share one qualification fingerprint")
    return complete


def build_research_plan(
    summary: dict[str, Any], *, shard_count: int = 10
) -> dict[str, Any]:
    if shard_count < 1 or shard_count > 100:
        raise ValueError("shard_count must be in [1, 100]")
    assets = verify_phase_48_2_summary(summary)
    source_fingerprint = str(summary["evidence_fingerprint"])
    strategy_fingerprint = str(assets[0]["strategy_fingerprint"])
    qualification_fingerprint = str(assets[0]["qualification_fingerprint"])
    dataset_bundle_fingerprint = _sha(
        [
            [str(item["base_asset"]).upper(), str(item["dataset_fingerprint"])]
            for item in assets
        ]
    )
    config_policy_fingerprint = _sha(
        [
            [str(item["base_asset"]).upper(), str(item["config_fingerprint"])]
            for item in assets
        ]
    )
    matrix = build_matrix(
        MatrixDimensions(
            dataset_versions=(dataset_bundle_fingerprint,),
            splits=("LOCKED_OOS", "WALK_FORWARD"),
            seeds=tuple(range(MATRIX_SEEDS)),
            strategy_fingerprints=(strategy_fingerprint,),
            config_fingerprints=(config_policy_fingerprint,),
            cost_scenarios=("PHASE_48_2_LOCKED_BASELINE",),
        )
    )
    if len(matrix) != MATRIX_RUN_COUNT:
        raise ValueError("real matrix must contain exactly 1,000 experiments")

    runs: list[dict[str, Any]] = []
    for run in matrix:
        asset_index = run.index % len(assets)
        asset = assets[asset_index]
        runs.append(
            {
                **asdict(run),
                "base_asset": str(asset["base_asset"]).upper(),
                "asset_index": asset_index,
                "shard": asset_index % shard_count,
                "asset_dataset_fingerprint": str(asset["dataset_fingerprint"]),
                "asset_config_fingerprint": str(asset["config_fingerprint"]),
                "asset_evidence_fingerprint": str(asset["evidence_fingerprint"]),
            }
        )

    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "phase": "48.3",
        "mode": "RESEARCH_PAPER_ONLY",
        "source_phase_48_2_evidence_fingerprint": source_fingerprint,
        "qualification_fingerprint": qualification_fingerprint,
        "dataset_bundle_fingerprint": dataset_bundle_fingerprint,
        "strategy_fingerprint": strategy_fingerprint,
        "config_policy_fingerprint": config_policy_fingerprint,
        "cost_scenarios": ["PHASE_48_2_LOCKED_BASELINE"],
        "seed_semantics": (
            "Deterministic reproducibility labels and walk-forward window selectors; "
            "stochastic resampling begins in Phase 48.4."
        ),
        "expected_runs": MATRIX_RUN_COUNT,
        "asset_count": len(assets),
        "excluded_performance_assets": ["SKY", "SPCX"],
        "shard_count": shard_count,
        "matrix_sha256": _sha([item.experiment_sha256 for item in matrix]),
        "runs": runs,
    }
    plan["plan_sha256"] = _sha(plan)
    return plan


def verify_plan(plan: dict[str, Any], summary: dict[str, Any]) -> None:
    if plan.get("schema") != PLAN_SCHEMA or plan.get("expected_runs") != MATRIX_RUN_COUNT:
        raise ValueError("invalid Phase 48.3 plan contract")
    claimed = str(plan.get("plan_sha256") or "")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if len(claimed) != 64 or _sha(unsigned) != claimed:
        raise ValueError("Phase 48.3 plan fingerprint is invalid")
    assets = verify_phase_48_2_summary(summary)
    if plan.get("source_phase_48_2_evidence_fingerprint") != summary.get(
        "evidence_fingerprint"
    ):
        raise ValueError("Phase 48.3 plan does not match its Phase 48.2 source")
    runs = plan.get("runs")
    if not isinstance(runs, list) or len(runs) != MATRIX_RUN_COUNT:
        raise ValueError("Phase 48.3 plan run count is invalid")
    indexes = [item.get("index") for item in runs if isinstance(item, dict)]
    if indexes != list(range(MATRIX_RUN_COUNT)):
        raise ValueError("Phase 48.3 run indexes are not contiguous")
    identities = [str(item.get("experiment_sha256") or "") for item in runs]
    if len(set(identities)) != MATRIX_RUN_COUNT or any(len(item) != 64 for item in identities):
        raise ValueError("Phase 48.3 experiment identities are invalid")
    if set(str(item["base_asset"]).upper() for item in runs) != {
        str(item["base_asset"]).upper() for item in assets
    }:
        raise ValueError("Phase 48.3 plan does not cover all executable assets")


def _parse_time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("matrix evaluation timestamp must be timezone-aware")
    return parsed


def _config(payload: dict[str, Any]) -> BacktestConfig:
    names = {
        "initial_equity",
        "risk_per_trade_percent",
        "max_aggregate_risk_percent",
        "max_futures_capital_percent",
        "commission_percent",
        "slippage_percent",
        "spread_percent",
        "funding_rate_percent_per_day",
        "allow_short",
    }
    unknown = set(payload) - names
    if unknown:
        raise ValueError(f"unknown BacktestConfig fields: {sorted(unknown)}")
    return BacktestConfig(
        initial_equity=Decimal(str(payload.get("initial_equity", "10000"))),
        risk_per_trade_percent=Decimal(str(payload.get("risk_per_trade_percent", "1"))),
        max_aggregate_risk_percent=Decimal(
            str(payload.get("max_aggregate_risk_percent", "4"))
        ),
        max_futures_capital_percent=Decimal(
            str(payload.get("max_futures_capital_percent", "50"))
        ),
        commission_percent=Decimal(str(payload.get("commission_percent", "0"))),
        slippage_percent=Decimal(str(payload.get("slippage_percent", "0"))),
        spread_percent=Decimal(str(payload.get("spread_percent", "0"))),
        funding_rate_percent_per_day=Decimal(
            str(payload.get("funding_rate_percent_per_day", "0"))
        ),
        allow_short=bool(payload.get("allow_short", True)),
    )


def _source_by_asset(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["base_asset"]).upper(): item
        for item in verify_phase_48_2_summary(summary)
    }


def _load_locked_asset(source: dict[str, Any]) -> tuple[dict[str, list[Any]], BacktestConfig]:
    qualification_key = str(source["qualification_object_key"])
    qualification = load_json(qualification_key)
    if _sha_payload(qualification) != source["qualification_fingerprint"]:
        raise ValueError("qualification fingerprint changed after Phase 48.2")
    manifest_keys = source.get("source_manifest_keys")
    if not isinstance(manifest_keys, list) or not manifest_keys:
        raise ValueError("Phase 48.2 asset is missing source manifests")
    manifests = [load_json(str(key)) for key in manifest_keys]
    qualification_asset = find_asset(qualification, str(source["base_asset"]))
    source_summary = select_source_summary(qualification_asset, manifests)
    candles, partition_evidence = load_candles(source_summary, str(source["symbol"]))
    partition_input = [
        {
            "object_key": row["object_key"],
            "sha256": row["sha256"],
            "timeframe": row["timeframe"],
        }
        for row in sorted(
            partition_evidence, key=lambda item: (item["timeframe"], item["object_key"])
        )
    ]
    actual_dataset = _sha_payload(
        {"qualification": source["qualification_fingerprint"], "partitions": partition_input}
    )
    if actual_dataset != source["dataset_fingerprint"]:
        raise ValueError("dataset fingerprint changed after Phase 48.2")
    strategy_rules = source.get("strategy_rules")
    if not isinstance(strategy_rules, dict) or _fingerprint(strategy_rules) != source[
        "strategy_fingerprint"
    ]:
        raise ValueError("strategy fingerprint changed after Phase 48.2")
    config_payload = source.get("backtest_config")
    if not isinstance(config_payload, dict) or _fingerprint(config_payload) != source[
        "config_fingerprint"
    ]:
        raise ValueError("config fingerprint changed after Phase 48.2")
    return candles, _config(config_payload)


def _evaluate(
    run: dict[str, Any], source: dict[str, Any], candles: dict[str, list[Any]], config: BacktestConfig
) -> dict[str, Any]:
    split = str(run["split"])
    if split == "LOCKED_OOS":
        evaluation_start = _parse_time(source["split"]["oos_start"])
        evaluation_end = _parse_time(source["split"]["oos_end"])
        window = None
    elif split == "WALK_FORWARD":
        windows = source.get("walk_forward", {}).get("windows", [])
        if not isinstance(windows, list) or not windows:
            raise ValueError("Phase 48.2 asset has no walk-forward windows")
        window = int(run["seed"]) % len(windows)
        selected = windows[window]
        evaluation_start = _parse_time(selected["test_start"])
        evaluation_end = _parse_time(selected["test_end"])
    else:
        raise ValueError(f"unsupported matrix split: {split}")
    result = BacktestEngine(config).run(
        str(source["symbol"]),
        _slice_to(candles, evaluation_end),
        evaluation_start=evaluation_start,
    )
    ready = _json_ready(
        {
            "experiment_sha256": run["experiment_sha256"],
            "run_index": run["index"],
            "base_asset": run["base_asset"],
            "symbol": source["symbol"],
            "split": split,
            "seed": run["seed"],
            "walk_forward_window_index": window,
            "evaluation_start": evaluation_start,
            "evaluation_end": evaluation_end,
            "cost_scenario": run["cost_scenario"],
            "dataset_fingerprint": source["dataset_fingerprint"],
            "strategy_fingerprint": source["strategy_fingerprint"],
            "config_fingerprint": source["config_fingerprint"],
            "metrics": _metrics(result),
        }
    )
    if not isinstance(ready, dict):
        raise TypeError("canonical matrix result must be an object")
    return ready


def _iter_attempts(root: Path | None) -> Iterable[dict[str, Any]]:
    if root is None or not root.exists():
        return ()
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"invalid checkpoint record: {path}")
            records.append(item)
    return records


def _latest_attempts(
    attempts: Iterable[dict[str, Any]], *, plan_sha256: str
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in attempts:
        if item.get("schema") != ATTEMPT_SCHEMA:
            raise ValueError("unsupported checkpoint schema")
        if item.get("plan_sha256") != plan_sha256:
            raise ValueError("checkpoint belongs to a different matrix plan")
        identity = str(item.get("experiment_sha256") or "")
        ordering = (
            int(item.get("workflow_run_id") or 0),
            int(item.get("workflow_attempt") or 0),
        )
        if ordering[0] < 1 or ordering[1] < 1:
            raise ValueError("checkpoint workflow identity is invalid")
        prior = latest.get(identity)
        prior_ordering = (
            int(prior.get("workflow_run_id") or 0),
            int(prior.get("workflow_attempt") or 0),
        ) if prior is not None else (0, 0)
        if prior is None or ordering > prior_ordering:
            latest[identity] = item
        elif ordering == prior_ordering and item != prior:
            raise ValueError("conflicting checkpoint records for one workflow attempt")
    return latest


def selected_runs(plan: dict[str, Any], *, scope: str, shard: int) -> list[dict[str, Any]]:
    runs = [item for item in plan["runs"] if isinstance(item, dict)]
    if scope == "smoke":
        runs = runs[:SMOKE_RUN_COUNT]
    elif scope != "full":
        raise ValueError("scope must be smoke or full")
    return [item for item in runs if int(item["shard"]) == shard]


def run_shard(
    *,
    plan: dict[str, Any],
    summary: dict[str, Any],
    shard: int,
    scope: str,
    workflow_run_id: int,
    workflow_attempt: int,
    output: Path,
    resume_root: Path | None = None,
) -> dict[str, int]:
    verify_plan(plan, summary)
    shard_count = int(plan["shard_count"])
    if not 0 <= shard < shard_count:
        raise ValueError("shard is outside the plan")
    if workflow_run_id < 1 or workflow_attempt < 1:
        raise ValueError("workflow run ID and attempt must be positive")
    runs = selected_runs(plan, scope=scope, shard=shard)
    expected = {str(item["experiment_sha256"]): item for item in runs}
    previous_all = list(_iter_attempts(resume_root))
    previous = _latest_attempts(previous_all, plan_sha256=str(plan["plan_sha256"]))
    unknown = set(previous) - {
        str(item["experiment_sha256"]) for item in plan["runs"]
    }
    if unknown:
        raise ValueError("resume evidence contains experiments outside the plan")
    sources = _source_by_asset(summary)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped = 0
    for identity, run in expected.items():
        prior = previous.get(identity)
        if prior is not None and prior.get("status") == "SUCCESS":
            skipped += 1
            continue
        grouped[str(run["base_asset"]).upper()].append(run)

    output.parent.mkdir(parents=True, exist_ok=True)
    succeeded = 0
    failed = 0
    with output.open("w", encoding="utf-8") as handle:
        for base_asset in sorted(grouped):
            source = sources[base_asset]
            try:
                candles, config = _load_locked_asset(source)
                load_error: Exception | None = None
            except Exception as exc:  # retained separately for every affected experiment
                candles = {}
                config = BacktestConfig()
                load_error = exc
            for run in sorted(grouped[base_asset], key=lambda item: int(item["index"])):
                try:
                    if load_error is not None:
                        raise load_error
                    result = _evaluate(run, source, candles, config)
                    result_sha = hashlib.sha256(_canonical_bytes(result)).hexdigest()
                    status = "SUCCESS"
                    error = None
                    succeeded += 1
                except Exception as exc:
                    result = None
                    result_sha = None
                    status = "FAILED"
                    error = f"{exc.__class__.__name__}:{str(exc)}"
                    failed += 1
                record = {
                    "schema": ATTEMPT_SCHEMA,
                    "plan_sha256": plan["plan_sha256"],
                    "matrix_sha256": plan["matrix_sha256"],
                    "workflow_run_id": workflow_run_id,
                    "workflow_attempt": workflow_attempt,
                    "shard": shard,
                    "run_index": run["index"],
                    "experiment_sha256": run["experiment_sha256"],
                    "status": status,
                    "result_sha256": result_sha,
                    "error": error,
                    "result": result,
                }
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
    return {
        "selected": len(runs),
        "skipped_successful": skipped,
        "attempted": succeeded + failed,
        "successful": succeeded,
        "failed": failed,
    }


def aggregate_attempts(
    *,
    plan: dict[str, Any],
    summary: dict[str, Any],
    roots: Iterable[Path],
    scope: str,
) -> dict[str, Any]:
    verify_plan(plan, summary)
    expected_runs = [item for item in plan["runs"] if isinstance(item, dict)]
    if scope == "smoke":
        expected_runs = expected_runs[:SMOKE_RUN_COUNT]
    elif scope != "full":
        raise ValueError("scope must be smoke or full")
    attempts = [item for root in roots for item in _iter_attempts(root)]
    latest = _latest_attempts(attempts, plan_sha256=str(plan["plan_sha256"]))
    expected_ids = {str(item["experiment_sha256"]) for item in expected_runs}
    selected = {key: value for key, value in latest.items() if key in expected_ids}
    missing = expected_ids - set(selected)
    if missing:
        raise ValueError(f"matrix evidence is missing {len(missing)} experiments")
    failed = sorted(key for key, item in selected.items() if item["status"] != "SUCCESS")
    ordered = [selected[str(item["experiment_sha256"])] for item in expected_runs]
    metrics = [item["result"]["metrics"] for item in ordered if item.get("result")]
    returns = [Decimal(str(item["total_return_percent"])) for item in metrics]
    trades = sum(int(item["trade_count"]) for item in metrics)
    latest_evidence = [
        {
            "experiment_sha256": item["experiment_sha256"],
            "workflow_run_id": item["workflow_run_id"],
            "workflow_attempt": item["workflow_attempt"],
            "status": item["status"],
            "result_sha256": item["result_sha256"],
            "error": item["error"],
        }
        for item in ordered
    ]
    report: dict[str, Any] = {
        "schema": SUMMARY_SCHEMA,
        "phase": "48.3",
        "mode": "RESEARCH_PAPER_ONLY",
        "status": (
            "PASS_SMOKE_EXECUTION_EVIDENCE"
            if scope == "smoke" and not failed
            else "PASS_1000_RUN_EXECUTION_EVIDENCE"
            if scope == "full" and not failed
            else "FAIL_MATRIX_EXECUTION_EVIDENCE"
        ),
        "scope": scope,
        "source_phase_48_2_evidence_fingerprint": summary["evidence_fingerprint"],
        "plan_sha256": plan["plan_sha256"],
        "matrix_sha256": plan["matrix_sha256"],
        "expected_runs": len(expected_runs),
        "completed_runs": len(selected),
        "successful_runs": len(selected) - len(failed),
        "failed_runs": len(failed),
        "failed_experiment_sha256": failed,
        "attempt_record_count": len(attempts),
        "total_trade_count": trades,
        "positive_return_run_count": sum(1 for value in returns if value > 0),
        "negative_return_run_count": sum(1 for value in returns if value < 0),
        "zero_return_run_count": sum(1 for value in returns if value == 0),
        "evidence_sha256": _sha(latest_evidence),
        "results": ordered,
        "limitations": (
            "Phase 48.3 proves real-engine matrix execution and reproducibility, not profitability.",
            "Seeds are deterministic experiment labels; stochastic bootstrap and Monte Carlo evidence begin in Phase 48.4.",
            "Repeated evaluations are not treated as independent market observations by final statistical qualification.",
            "SKY and SPCX remain performance-excluded until real warm-up history exists.",
        ),
    }
    report["report_sha256"] = _sha(report)
    return report


def _find_summary(root: Path) -> Path:
    candidates = sorted(root.rglob("summary.json"))
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one summary.json under {root}, got {len(candidates)}")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--phase-48-2-root", type=Path, required=True)
    plan_parser.add_argument("--shard-count", type=int, default=10)
    plan_parser.add_argument("--output", type=Path, required=True)

    shard_parser = commands.add_parser("shard")
    shard_parser.add_argument("--plan", type=Path, required=True)
    shard_parser.add_argument("--phase-48-2-summary", type=Path, required=True)
    shard_parser.add_argument("--shard", type=int, required=True)
    shard_parser.add_argument("--scope", choices=("smoke", "full"), required=True)
    shard_parser.add_argument("--workflow-run-id", type=int, required=True)
    shard_parser.add_argument("--workflow-attempt", type=int, required=True)
    shard_parser.add_argument("--output", type=Path, required=True)
    shard_parser.add_argument("--resume-root", type=Path)

    aggregate_parser = commands.add_parser("aggregate")
    aggregate_parser.add_argument("--plan", type=Path, required=True)
    aggregate_parser.add_argument("--phase-48-2-summary", type=Path, required=True)
    aggregate_parser.add_argument("--attempt-root", type=Path, action="append", required=True)
    aggregate_parser.add_argument("--scope", choices=("smoke", "full"), required=True)
    aggregate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "plan":
        source_path = _find_summary(args.phase_48_2_root)
        summary = _read_json(source_path)
        report = build_research_plan(summary, shard_count=args.shard_count)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"plan_sha256": report["plan_sha256"], "runs": report["expected_runs"]}))
        return 0

    plan = _read_json(args.plan)
    summary = _read_json(args.phase_48_2_summary)
    if args.command == "shard":
        stats = run_shard(
            plan=plan,
            summary=summary,
            shard=args.shard,
            scope=args.scope,
            workflow_run_id=args.workflow_run_id,
            workflow_attempt=args.workflow_attempt,
            output=args.output,
            resume_root=args.resume_root,
        )
        print(json.dumps(stats, sort_keys=True))
        return 1 if stats["failed"] else 0

    report = aggregate_attempts(
        plan=plan,
        summary=summary,
        roots=args.attempt_root,
        scope=args.scope,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "completed_runs", "failed_runs", "report_sha256")}, sort_keys=True))
    return 1 if report["failed_runs"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
