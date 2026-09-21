import json
from pathlib import Path

import pytest

from scripts.backtest.run_phase_48_4_robustness import _sha, build_plan as build_48_4_plan
from scripts.backtest.run_phase_48_5_synthetic import (
    _validate_trade_indices,
    aggregate,
    build_plan,
    extract_unique_ledgers,
    run_shard,
    verify_quality_gates,
    verify_source_bundle,
)
from tests.backtest.test_phase_48_4_real_robustness import _source as phase_48_3_source


def _bundle() -> tuple[dict, dict, dict]:
    source = phase_48_3_source()
    for attempt in source["results"]:
        result = attempt["result"]
        trades = result["metrics"]["trades"]
        for index, trade in enumerate(trades, 1):
            trade.update(
                {
                    "trade_index": index,
                    "direction": "LONG" if index % 2 else "SHORT",
                    "entry_price": str(100 + index),
                    "exit_price": str(102 + index if index % 2 else 99 + index),
                    "quantity": "5",
                    "commission": "1",
                    "funding_cost": "0.25",
                }
            )
        attempt["result_sha256"] = _sha(result)
    evidence = [
        {
            "experiment_sha256": item["experiment_sha256"],
            "workflow_run_id": item["workflow_run_id"],
            "workflow_attempt": item["workflow_attempt"],
            "status": item["status"],
            "result_sha256": item["result_sha256"],
            "error": item["error"],
        }
        for item in source["results"]
    ]
    source["evidence_sha256"] = _sha(evidence)
    source.pop("report_sha256")
    source["report_sha256"] = _sha(source)
    plan_48_4 = build_48_4_plan(source)
    summary = {
        "schema": "phase-48-4-robustness-summary-v1",
        "phase": "48.4",
        "status": "PASS_ROBUSTNESS_EXECUTION_EVIDENCE",
        "scope": "full",
        "simulation_count": 10_000,
        "plan_sha256": plan_48_4["plan_sha256"],
        "source_phase_48_3_evidence_sha256": source["evidence_sha256"],
        "results_evidence_sha256": "9" * 64,
    }
    summary["report_sha256"] = _sha(summary)
    return summary, plan_48_4, source


def test_source_chain_ledgers_and_corruption_gates_are_verified() -> None:
    summary, plan_48_4, source = _bundle()
    verify_source_bundle(summary, plan_48_4, source)
    ledgers = extract_unique_ledgers(source)
    outcomes = verify_quality_gates(ledgers)

    assert len(ledgers) == 8
    assert outcomes == {
        "original_ledger_pass_count": 8,
        "duplicate_corruption_rejected_count": 8,
        "missing_corruption_rejected_count": 8,
    }


def test_empty_ledger_is_rejected_after_single_trade_is_removed() -> None:
    with pytest.raises(ValueError, match="missing"):
        _validate_trade_indices(())


def test_full_plan_has_10000_unique_scenarios_and_all_modes() -> None:
    summary, plan_48_4, source = _bundle()
    plan = build_plan(summary, plan_48_4, source)

    assert plan["scenario_count"] == 10_000
    assert len({item["scenario_sha256"] for item in plan["scenarios"]}) == 10_000
    assert {item["scenario_mode"] for item in plan["scenarios"]} == {
        "PRICE_NOISE_5_BPS",
        "PRICE_NOISE_10_BPS",
        "PRICE_NOISE_25_BPS",
        "PRICE_NOISE_50_BPS",
        "SYNTHETIC_GBM",
        "SYNTHETIC_JUMP_DIFFUSION",
        "SYNTHETIC_VOLATILITY_CLUSTER",
        "SYNTHETIC_REGIME_SWITCHING",
    }


def test_smoke_covers_noise_and_synthetic_paths_and_aggregates(tmp_path: Path) -> None:
    summary, plan_48_4, source = _bundle()
    plan = build_plan(summary, plan_48_4, source)
    root = tmp_path / "results"
    root.mkdir()
    total = 0
    for shard in range(10):
        results = run_shard(
            plan, summary, plan_48_4, source, shard=shard, scope="smoke"
        )
        total += len(results)
        (root / f"shard-{shard}.jsonl").write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in results),
            encoding="utf-8",
        )

    report = aggregate(
        plan, summary, plan_48_4, source, roots=[root], scope="smoke"
    )

    assert total == 100
    assert report["status"] == "PASS_SYNTHETIC_ROBUSTNESS_SMOKE"
    assert report["scenario_count"] == 100
    assert report["price_noise_scenario_count"] > 0
    assert report["synthetic_path_scenario_count"] > 0
    assert report["price_noise_ruin_count"] == 0
    assert len(report["scenario_mode_counts"]) == 8


def test_phase_48_4_summary_mutation_fails_closed() -> None:
    summary, plan_48_4, source = _bundle()
    summary["simulation_count"] = 9999

    with pytest.raises(ValueError, match="complete|fingerprint"):
        verify_source_bundle(summary, plan_48_4, source)
