import json
from pathlib import Path

import pytest

from app.backtest.robustness_sampling import SamplingMode
from scripts.backtest.run_phase_48_4_robustness import (
    _sha,
    aggregate,
    build_plan,
    extract_unique_trade_paths,
    run_shard,
    verify_source,
)


def _source() -> dict:
    attempts = []
    for index in range(1000):
        asset = f"ASSET{index % 2}"
        split = "LOCKED_OOS" if (index // 2) % 2 == 0 else "WALK_FORWARD"
        window = None if split == "LOCKED_OOS" else index % 3
        trades = [
            {"entry_time": "2026-01-01T00:00:00+00:00", "realized_pnl": "10"},
            {"entry_time": "2026-01-02T00:00:00+00:00", "realized_pnl": "-6"},
            {"entry_time": "2026-01-03T00:00:00+00:00", "realized_pnl": "4"},
        ]
        result = {
            "experiment_sha256": f"{index + 1:064x}",
            "run_index": index,
            "base_asset": asset,
            "symbol": f"{asset}/USDT",
            "split": split,
            "seed": index // 2,
            "walk_forward_window_index": window,
            "dataset_fingerprint": ("a" if asset == "ASSET0" else "b") * 64,
            "strategy_fingerprint": "c" * 64,
            "config_fingerprint": "d" * 64,
            "metrics": {
                "initial_equity": "10000",
                "trade_count": 3,
                "total_return_percent": "0.08",
                "trades": trades,
            },
        }
        attempts.append(
            {
                "schema": "phase-48-3-real-matrix-attempt-v1",
                "plan_sha256": "e" * 64,
                "matrix_sha256": "f" * 64,
                "workflow_run_id": 123,
                "workflow_attempt": 1,
                "shard": index % 10,
                "run_index": index,
                "experiment_sha256": result["experiment_sha256"],
                "status": "SUCCESS",
                "result_sha256": _sha(result),
                "error": None,
                "result": result,
            }
        )
    evidence = [
        {
            "experiment_sha256": item["experiment_sha256"],
            "workflow_run_id": item["workflow_run_id"],
            "workflow_attempt": item["workflow_attempt"],
            "status": item["status"],
            "result_sha256": item["result_sha256"],
            "error": item["error"],
        }
        for item in attempts
    ]
    source = {
        "schema": "phase-48-3-real-matrix-summary-v1",
        "status": "PASS_1000_RUN_EXECUTION_EVIDENCE",
        "expected_runs": 1000,
        "completed_runs": 1000,
        "successful_runs": 1000,
        "failed_runs": 0,
        "evidence_sha256": _sha(evidence),
        "results": attempts,
    }
    source["report_sha256"] = _sha(source)
    return source


def test_source_is_verified_and_repeated_matrix_runs_are_collapsed() -> None:
    source = _source()
    verify_source(source)
    paths = extract_unique_trade_paths(source)

    assert len(paths) == 8
    assert all(item["trade_count"] == 3 for item in paths)


def test_real_plan_contains_10000_unique_simulations_and_all_modes() -> None:
    plan = build_plan(_source())

    assert plan["simulation_count"] == 10_000
    assert len(plan["simulations"]) == 10_000
    assert len({item["simulation_sha256"] for item in plan["simulations"]}) == 10_000
    assert {item["sampling_mode"] for item in plan["simulations"]} == {
        mode.value for mode in SamplingMode
    }


def test_smoke_runs_all_sampling_modes_and_aggregates(tmp_path: Path) -> None:
    source = _source()
    plan = build_plan(source)
    root = tmp_path / "results"
    root.mkdir()
    total = 0
    for shard in range(10):
        results = run_shard(plan, source, shard=shard, scope="smoke")
        total += len(results)
        (root / f"shard-{shard}.jsonl").write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in results),
            encoding="utf-8",
        )

    report = aggregate(plan, source, roots=[root], scope="smoke")

    assert total == 100
    assert report["status"] == "PASS_ROBUSTNESS_SMOKE"
    assert report["simulation_count"] == 100
    assert set(report["sampling_mode_counts"]) == {mode.value for mode in SamplingMode}
    assert report["ruin_count"] == 0


def test_source_mutation_fails_closed() -> None:
    source = _source()
    source["completed_runs"] = 999

    with pytest.raises(ValueError, match="complete|fingerprint"):
        verify_source(source)
