import json
from dataclasses import asdict
from pathlib import Path

import pytest

from app.backtest.models import BacktestConfig
from app.strategy.rules import DEFAULT_RULES
from scripts.backtest.run_phase_48_2_locked_oos import _fingerprint
from scripts.backtest.run_phase_48_3_matrix import _sha, build_research_plan
from scripts.backtest.run_phase_48_4_robustness import build_plan as build_48_4_plan
from scripts.backtest.run_phase_48_5_synthetic import build_plan as build_48_5_plan
from scripts.backtest.run_phase_48_6_parameter_stability import (
    RESULT_SCHEMA,
    _selected,
    aggregate,
    build_plan,
    verify_phase_48_5_bundle,
    verify_source_chain,
)
from tests.backtest.test_phase_48_3_real_matrix import _source_summary
from tests.backtest.test_phase_48_4_real_robustness import _source as phase_48_3_source


def _bundle() -> tuple[dict, dict, dict, dict, dict]:
    source_48_2 = _source_summary()
    strategy_payload = asdict(DEFAULT_RULES)
    config_payload = asdict(BacktestConfig())
    strategy_fingerprint = _fingerprint(strategy_payload)
    config_fingerprint = _fingerprint(config_payload)
    for item in source_48_2["assets"]:
        if item["execution_status"] != "COMPLETE":
            continue
        item.update(
            {
                "symbol": f"{item['base_asset']}/USDT",
                "strategy_fingerprint": strategy_fingerprint,
                "config_fingerprint": config_fingerprint,
                "strategy_rules": strategy_payload,
                "backtest_config": config_payload,
                "split": {
                    "oos_start": "2026-02-01T00:00:00+00:00",
                    "oos_end": "2026-03-01T00:00:00+00:00",
                },
                "walk_forward": {
                    "windows": [
                        {
                            "test_start": f"2026-01-0{index + 1}T00:00:00+00:00",
                            "test_end": f"2026-01-0{index + 2}T00:00:00+00:00",
                        }
                        for index in range(3)
                    ]
                },
            }
        )
    source_48_2.pop("evidence_fingerprint")
    source_48_2["evidence_fingerprint"] = _sha(source_48_2)
    plan_48_3 = build_research_plan(source_48_2)

    summary_48_3 = phase_48_3_source()
    for attempt in summary_48_3["results"]:
        result = attempt["result"]
        old = result["base_asset"]
        base = "ASSET00" if old == "ASSET0" else "ASSET01"
        source = next(
            item for item in source_48_2["assets"] if item.get("base_asset") == base
        )
        result.update(
            {
                "base_asset": base,
                "symbol": source["symbol"],
                "dataset_fingerprint": source["dataset_fingerprint"],
                "strategy_fingerprint": strategy_fingerprint,
                "config_fingerprint": config_fingerprint,
            }
        )
        for index, trade in enumerate(result["metrics"]["trades"], 1):
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
        attempt["plan_sha256"] = plan_48_3["plan_sha256"]
        attempt["matrix_sha256"] = plan_48_3["matrix_sha256"]
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
        for item in summary_48_3["results"]
    ]
    summary_48_3.update(
        {
            "plan_sha256": plan_48_3["plan_sha256"],
            "matrix_sha256": plan_48_3["matrix_sha256"],
            "evidence_sha256": _sha(evidence),
        }
    )
    summary_48_3.pop("report_sha256")
    summary_48_3["report_sha256"] = _sha(summary_48_3)

    plan_48_4 = build_48_4_plan(summary_48_3)
    summary_48_4 = {
        "schema": "phase-48-4-robustness-summary-v1",
        "phase": "48.4",
        "status": "PASS_ROBUSTNESS_EXECUTION_EVIDENCE",
        "scope": "full",
        "simulation_count": 10_000,
        "plan_sha256": plan_48_4["plan_sha256"],
        "source_phase_48_3_evidence_sha256": summary_48_3["evidence_sha256"],
        "results_evidence_sha256": "9" * 64,
    }
    summary_48_4["report_sha256"] = _sha(summary_48_4)
    plan_48_5 = build_48_5_plan(summary_48_4, plan_48_4, summary_48_3)
    summary_48_5 = {
        "schema": "phase-48-5-synthetic-summary-v1",
        "phase": "48.5",
        "status": "PASS_SYNTHETIC_ROBUSTNESS_EXECUTION_EVIDENCE",
        "scope": "full",
        "scenario_count": 10_000,
        "unique_observed_trade_ledger_count": len(plan_48_5["ledgers"]),
        "plan_sha256": plan_48_5["plan_sha256"],
        "source_phase_48_4_report_sha256": summary_48_4["report_sha256"],
        "source_phase_48_4_results_evidence_sha256": summary_48_4[
            "results_evidence_sha256"
        ],
        "source_phase_48_3_evidence_sha256": summary_48_3["evidence_sha256"],
        "results_evidence_sha256": "8" * 64,
    }
    summary_48_5["report_sha256"] = _sha(summary_48_5)
    return summary_48_5, plan_48_5, summary_48_3, plan_48_3, source_48_2


def test_real_plan_connects_full_chain_and_builds_true_rule_sweeps() -> None:
    bundle = _bundle()
    plan = build_plan(*bundle)

    assert plan["scenario_count"] == 13
    assert plan["ledger_count"] == 8
    assert plan["evaluation_count"] == 104
    assert {item["parameter"] for item in plan["scenarios"]} == {
        "BASELINE",
        "min_rr",
        "min_score",
        "min_confidence",
    }
    assert len({item["evaluation_sha256"] for item in plan["evaluations"]}) == 104
    assert plan["source_phase_48_5_report_sha256"] == bundle[0]["report_sha256"]


def test_smoke_selects_every_scenario_and_aggregates_execution_evidence(
    tmp_path: Path,
) -> None:
    plan = build_plan(*_bundle())
    selected = _selected(plan, "smoke")
    assert {item["scenario_index"] for item in selected} == set(range(13))
    root = tmp_path / "results"
    root.mkdir()
    records = []
    for item in selected:
        scenario = plan["scenarios"][item["scenario_index"]]
        record = {
            "schema": RESULT_SCHEMA,
            "plan_sha256": plan["plan_sha256"],
            "evaluation_sha256": item["evaluation_sha256"],
            "scenario_sha256": scenario["scenario_sha256"],
            "ledger_sha256": plan["ledgers"][item["ledger_index"]]["ledger_sha256"],
            "scenario_index": item["scenario_index"],
            "ledger_index": item["ledger_index"],
            "base_asset": plan["ledgers"][item["ledger_index"]]["base_asset"],
            "split": plan["ledgers"][item["ledger_index"]]["split"],
            "walk_forward_window_index": plan["ledgers"][item["ledger_index"]][
                "walk_forward_window_index"
            ],
            "parameter": scenario["parameter"],
            "requested_perturbation": scenario["requested_perturbation"],
            "rules": scenario["rules"],
            "metrics": {
                "initial_equity": "10000",
                "final_equity": "10010",
                "trade_count": 2,
                "max_drawdown_percent": "1",
                "win_rate_percent": "50",
                "profit_factor": "1.1",
                "total_return_percent": "0.1",
                "expectancy_pnl": "5",
            },
        }
        record["result_sha256"] = _sha(record)
        records.append(record)
    (root / "results.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )

    report = aggregate(plan, roots=[root], scope="smoke")

    assert report["status"] == "PASS_PARAMETER_STABILITY_SMOKE"
    assert report["evaluation_count"] == len(selected)
    assert report["stability_passed"] is True
    assert report["scenario_count"] == 13
    assert len(report["report_sha256"]) == 64


def test_mutated_phase_48_5_and_broken_chain_fail_closed() -> None:
    summary_48_5, plan_48_5, summary_48_3, plan_48_3, source_48_2 = _bundle()
    summary_48_5["scenario_count"] = 9999
    with pytest.raises(ValueError, match="complete|fingerprint"):
        verify_phase_48_5_bundle(summary_48_5, plan_48_5)

    summary_48_5, plan_48_5, summary_48_3, plan_48_3, source_48_2 = _bundle()
    plan_48_5["source_phase_48_3_evidence_sha256"] = "0" * 64
    plan_48_5.pop("plan_sha256")
    plan_48_5["plan_sha256"] = _sha(plan_48_5)
    summary_48_5["plan_sha256"] = plan_48_5["plan_sha256"]
    summary_48_5.pop("report_sha256")
    summary_48_5["report_sha256"] = _sha(summary_48_5)
    with pytest.raises(ValueError, match="chain|match"):
        verify_source_chain(
            summary_48_5, plan_48_5, summary_48_3, plan_48_3, source_48_2
        )
