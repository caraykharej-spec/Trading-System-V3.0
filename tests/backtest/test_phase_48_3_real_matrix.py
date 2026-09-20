import json
from collections import Counter
from pathlib import Path

import pytest

from scripts.backtest.run_phase_48_3_matrix import (
    ATTEMPT_SCHEMA,
    SMOKE_RUN_COUNT,
    _sha,
    aggregate_attempts,
    build_research_plan,
    verify_phase_48_2_summary,
)


def _source_summary() -> dict:
    complete = []
    for index in range(79):
        base = f"ASSET{index:02d}"
        complete.append(
            {
                "execution_status": "COMPLETE",
                "base_asset": base,
                "dataset_fingerprint": f"{index + 1:064x}",
                "strategy_fingerprint": "1" * 64,
                "config_fingerprint": f"{index + 101:064x}",
                "qualification_fingerprint": "2" * 64,
                "evidence_fingerprint": f"{index + 201:064x}",
            }
        )
    assets = [
        *complete,
        {"execution_status": "WARMUP_PENDING", "base_asset": "SKY"},
        {"execution_status": "WARMUP_PENDING", "base_asset": "SPCX"},
    ]
    summary = {
        "schema": "phase-48-2-locked-oos-summary-v1",
        "status": "PASS_EXECUTION_EVIDENCE",
        "asset_report_count": 81,
        "executed_asset_count": 79,
        "warmup_pending_asset_count": 2,
        "warmup_pending_assets": ["SKY", "SPCX"],
        "assets": assets,
    }
    summary["evidence_fingerprint"] = _sha(summary)
    return summary


def _attempt(plan: dict, run: dict, *, run_id: int, status: str = "SUCCESS") -> dict:
    result = None
    result_sha = None
    error = "RuntimeError:transient" if status == "FAILED" else None
    if status == "SUCCESS":
        result = {
            "metrics": {
                "trade_count": 2,
                "total_return_percent": "1.5",
            }
        }
        result_sha = _sha(result)
    return {
        "schema": ATTEMPT_SCHEMA,
        "plan_sha256": plan["plan_sha256"],
        "matrix_sha256": plan["matrix_sha256"],
        "workflow_run_id": run_id,
        "workflow_attempt": 1,
        "shard": run["shard"],
        "run_index": run["index"],
        "experiment_sha256": run["experiment_sha256"],
        "status": status,
        "result_sha256": result_sha,
        "error": error,
        "result": result,
    }


def _write_attempts(root: Path, records: list[dict]) -> None:
    root.mkdir(parents=True)
    (root / "checkpoint.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )


def test_real_plan_is_exactly_1000_and_balances_all_executable_assets() -> None:
    summary = _source_summary()
    plan = build_research_plan(summary, shard_count=10)

    assert plan["expected_runs"] == 1000
    assert len(plan["runs"]) == 1000
    assert len({item["experiment_sha256"] for item in plan["runs"]}) == 1000
    assert {item["split"] for item in plan["runs"]} == {
        "LOCKED_OOS",
        "WALK_FORWARD",
    }
    assert {item["seed"] for item in plan["runs"]} == set(range(500))
    assert plan["excluded_performance_assets"] == ["SKY", "SPCX"]
    coverage = Counter(item["base_asset"] for item in plan["runs"])
    assert len(coverage) == 79
    assert max(coverage.values()) - min(coverage.values()) <= 1
    assert {item["shard"] for item in plan["runs"]} == set(range(10))


def test_source_fingerprint_mismatch_fails_closed() -> None:
    summary = _source_summary()
    summary["status"] = "MUTATED_AFTER_SEAL"

    with pytest.raises(ValueError, match="not PASS|fingerprint"):
        verify_phase_48_2_summary(summary)


def test_smoke_aggregate_accepts_complete_real_attempts(tmp_path: Path) -> None:
    summary = _source_summary()
    plan = build_research_plan(summary)
    root = tmp_path / "attempts"
    records = [_attempt(plan, item, run_id=100) for item in plan["runs"][:SMOKE_RUN_COUNT]]
    _write_attempts(root, records)

    report = aggregate_attempts(
        plan=plan,
        summary=summary,
        roots=[root],
        scope="smoke",
    )

    assert report["status"] == "PASS_SMOKE_EXECUTION_EVIDENCE"
    assert report["completed_runs"] == 10
    assert report["successful_runs"] == 10
    assert report["failed_runs"] == 0
    assert report["total_trade_count"] == 20


def test_resume_keeps_failed_attempt_and_uses_later_success(tmp_path: Path) -> None:
    summary = _source_summary()
    plan = build_research_plan(summary)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    smoke = plan["runs"][:SMOKE_RUN_COUNT]
    first = [
        _attempt(plan, item, run_id=100, status="FAILED" if index == 0 else "SUCCESS")
        for index, item in enumerate(smoke)
    ]
    retry = [_attempt(plan, smoke[0], run_id=101)]
    _write_attempts(first_root, first)
    _write_attempts(second_root, retry)

    report = aggregate_attempts(
        plan=plan,
        summary=summary,
        roots=[first_root, second_root],
        scope="smoke",
    )

    assert report["status"] == "PASS_SMOKE_EXECUTION_EVIDENCE"
    assert report["attempt_record_count"] == 11
    assert report["successful_runs"] == 10
    assert report["failed_runs"] == 0
    first_result = next(
        item for item in report["results"] if item["experiment_sha256"] == smoke[0]["experiment_sha256"]
    )
    assert first_result["workflow_run_id"] == 101


def test_missing_smoke_experiment_fails_closed(tmp_path: Path) -> None:
    summary = _source_summary()
    plan = build_research_plan(summary)
    root = tmp_path / "attempts"
    records = [_attempt(plan, item, run_id=100) for item in plan["runs"][:9]]
    _write_attempts(root, records)

    with pytest.raises(ValueError, match="missing 1 experiments"):
        aggregate_attempts(plan=plan, summary=summary, roots=[root], scope="smoke")
