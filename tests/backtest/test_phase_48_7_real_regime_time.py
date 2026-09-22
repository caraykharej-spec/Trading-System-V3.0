import json
from pathlib import Path

import pytest

from scripts.backtest.run_phase_48_4_robustness import _sha
from scripts.backtest.run_phase_48_6_parameter_stability import (
    build_plan as build_48_6_plan,
)
from scripts.backtest.run_phase_48_7_regime_time import (
    RESULT_SCHEMA,
    _selected,
    aggregate,
    build_plan,
    verify_phase_48_6_bundle,
    verify_source_chain,
)
from tests.backtest.test_phase_48_6_real_parameter_stability import _bundle


def _real_bundle() -> tuple[dict, dict, dict, dict, dict]:
    summary_48_5, plan_48_5, summary_48_3, plan_48_3, source_48_2 = _bundle()
    plan_48_6 = build_48_6_plan(
        summary_48_5,
        plan_48_5,
        summary_48_3,
        plan_48_3,
        source_48_2,
    )
    summary_48_6 = {
        "schema": "phase-48-6-parameter-summary-v1",
        "phase": "48.6",
        "status": "PASS_PARAMETER_STABILITY_EXECUTION_EVIDENCE",
        "scope": "full",
        "source_phase_48_5_report_sha256": summary_48_5["report_sha256"],
        "source_phase_48_5_results_evidence_sha256": summary_48_5[
            "results_evidence_sha256"
        ],
        "source_phase_48_3_evidence_sha256": summary_48_3["evidence_sha256"],
        "plan_sha256": plan_48_6["plan_sha256"],
        "scenario_count": 13,
        "evaluation_count": plan_48_6["evaluation_count"],
        "stability_passed": True,
        "results_evidence_sha256": "7" * 64,
    }
    summary_48_6["report_sha256"] = _sha(summary_48_6)
    return summary_48_6, plan_48_6, summary_48_3, plan_48_3, source_48_2


def test_real_plan_connects_passed_phase_48_6_to_unique_ledgers() -> None:
    bundle = _real_bundle()

    plan = build_plan(*bundle)

    assert plan["ledger_count"] == 8
    assert plan["evaluation_count"] == 8
    assert len({item["evaluation_sha256"] for item in plan["evaluations"]}) == 8
    assert plan["source_phase_48_6_report_sha256"] == bundle[0]["report_sha256"]
    assert plan["coverage_thresholds"]["min_regime_trade_count"] == 5


def test_full_aggregate_uses_trade_regime_slices_and_coverage(tmp_path: Path) -> None:
    plan = build_plan(*_real_bundle())
    selected = _selected(plan, "full")
    root = tmp_path / "results"
    root.mkdir()
    records = []
    for item in selected:
        ledger = plan["ledgers"][item["ledger_index"]]
        regime = "TRENDING_BULL" if item["ledger_index"] % 2 == 0 else "RANGING"
        record = {
            "schema": RESULT_SCHEMA,
            "plan_sha256": plan["plan_sha256"],
            "evaluation_sha256": item["evaluation_sha256"],
            "ledger_sha256": ledger["ledger_sha256"],
            "ledger_index": item["ledger_index"],
            "base_asset": ledger["base_asset"],
            "split": ledger["split"],
            "walk_forward_window_index": ledger["walk_forward_window_index"],
            "evaluation_start": ledger["evaluation_start"],
            "evaluation_end": ledger["evaluation_end"],
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
            "decision_point_count": 100,
            "regime_attribution": {
                "trade_performance_by_entry_regime": {
                    regime: {
                        "trade_count": 2,
                        "net_pnl": "10",
                        "net_pnl_percent_initial_equity": "0.1",
                    }
                }
            },
        }
        record["result_sha256"] = _sha(record)
        records.append(record)
    (root / "results.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )

    report = aggregate(plan, roots=[root], scope="full")

    assert report["status"] == "PASS_REGIME_TIME_EXECUTION_EVIDENCE"
    assert report["evaluation_count"] == 8
    assert report["zero_trade_ledger_count"] == 0
    assert report["coverage_passed"] is True
    assert report["regime_time_passed"] is True
    assert report["robustness_passed"] is True


def test_zero_trade_ledger_is_coverage_gap_not_flat_score(tmp_path: Path) -> None:
    plan = build_plan(*_real_bundle())
    plan["coverage_thresholds"]["min_regime_trade_count"] = 1
    plan["coverage_thresholds"]["min_qualified_regimes"] = 1
    plan["coverage_thresholds"]["min_active_time_cohorts"] = 1
    plan.pop("plan_sha256")
    plan["plan_sha256"] = _sha(plan)
    selected = _selected(plan, "smoke")
    root = tmp_path / "results"
    root.mkdir()
    records = []
    for index, item in enumerate(selected):
        ledger = plan["ledgers"][item["ledger_index"]]
        active = index > 0
        performance = (
            {
                "TRENDING_BULL": {
                    "trade_count": 1,
                    "net_pnl": "1",
                    "net_pnl_percent_initial_equity": "0.01",
                }
            }
            if active
            else {}
        )
        record = {
            "schema": RESULT_SCHEMA,
            "plan_sha256": plan["plan_sha256"],
            "evaluation_sha256": item["evaluation_sha256"],
            "ledger_sha256": ledger["ledger_sha256"],
            "ledger_index": item["ledger_index"],
            "base_asset": ledger["base_asset"],
            "split": ledger["split"],
            "walk_forward_window_index": ledger["walk_forward_window_index"],
            "evaluation_start": ledger["evaluation_start"],
            "evaluation_end": ledger["evaluation_end"],
            "metrics": {
                "initial_equity": "10000",
                "final_equity": "10001" if active else "10000",
                "trade_count": 1 if active else 0,
                "max_drawdown_percent": "0",
                "win_rate_percent": "100" if active else "0",
                "profit_factor": None,
                "total_return_percent": "0.01" if active else "0",
                "expectancy_pnl": "1" if active else "0",
            },
            "decision_point_count": 100,
            "regime_attribution": {
                "trade_performance_by_entry_regime": performance
            },
        }
        record["result_sha256"] = _sha(record)
        records.append(record)
    (root / "results.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )

    report = aggregate(plan, roots=[root], scope="smoke")

    assert report["zero_trade_ledger_count"] == 1
    assert report["performance_slice_count"] == len(selected) - 1


def test_failed_or_mutated_phase_48_6_fails_closed() -> None:
    summary_48_6, plan_48_6, summary_48_3, plan_48_3, source_48_2 = _real_bundle()
    summary_48_6["stability_passed"] = False
    summary_48_6.pop("report_sha256")
    summary_48_6["report_sha256"] = _sha(summary_48_6)
    with pytest.raises(ValueError, match="did not pass"):
        verify_phase_48_6_bundle(summary_48_6, plan_48_6)

    summary_48_6, plan_48_6, summary_48_3, plan_48_3, source_48_2 = _real_bundle()
    plan_48_6["source_phase_48_3_evidence_sha256"] = "0" * 64
    plan_48_6.pop("plan_sha256")
    plan_48_6["plan_sha256"] = _sha(plan_48_6)
    summary_48_6["plan_sha256"] = plan_48_6["plan_sha256"]
    summary_48_6.pop("report_sha256")
    summary_48_6["report_sha256"] = _sha(summary_48_6)
    with pytest.raises(ValueError, match="Phase 48.3"):
        verify_source_chain(
            summary_48_6, plan_48_6, summary_48_3, plan_48_3, source_48_2
        )
