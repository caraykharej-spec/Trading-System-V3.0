"""Run real Phase 48.7 regime and time robustness evidence.

The executor verifies the completed Phase 48.6 parameter-stability report and
the locked Phase 48.3/48.2 baseline chain. It then replays each unique locked
ledger once with the unchanged baseline rules, attributes actual trades to
no-lookahead daily regimes, and evaluates independent chronological series per
asset and regime. Zero-trade ledgers are reported as coverage gaps and are not
treated as neutral performance observations.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from app.backtest.diagnostics import BacktestDiagnosticEvent, SignalAttritionDiagnostics
from app.backtest.engine import BacktestEngine
from app.backtest.locked_baseline_runner import _validate_diagnostics
from app.backtest.regime_attribution import (
    attribute_regime_evidence,
    build_daily_regime_timeline,
    validate_regime_attribution,
)
from app.backtest.regime_time_robustness import (
    RegimeTimeSlice,
    RegimeTimeThresholds,
    qualify_regime_time_robustness,
)
from app.strategy.rules import StrategyRules
from app.strategy_validation.models import StrategyValidationPolicy
from scripts.backtest.run_phase_48_2_locked_oos import _metrics, _slice_to
from scripts.backtest.run_phase_48_3_matrix import (
    _load_locked_asset,
    _parse_time,
    verify_phase_48_2_summary,
    verify_plan as verify_phase_48_3_plan,
)
from scripts.backtest.run_phase_48_4_robustness import (
    _sha,
    extract_unique_trade_paths,
    verify_source as verify_phase_48_3_summary,
)
from scripts.backtest.run_phase_48_6_parameter_stability import (
    PLAN_SCHEMA as PHASE_48_6_PLAN_SCHEMA,
    verify_plan as verify_phase_48_6_plan,
)

PHASE_48_6_SUMMARY_SCHEMA = "phase-48-6-parameter-summary-v1"
PLAN_SCHEMA = "phase-48-7-regime-time-plan-v1"
RESULT_SCHEMA = "phase-48-7-regime-time-result-v1"
SUMMARY_SCHEMA = "phase-48-7-regime-time-summary-v1"
SHARD_COUNT = 10
SMOKE_ASSET_COUNT = 8


def _ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(key): _ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_ready(item) for item in value]
    return value


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _one(root: Path, name: str) -> dict[str, Any]:
    paths = sorted(root.rglob(name))
    if len(paths) != 1:
        raise ValueError(f"expected one {name} under {root}, got {len(paths)}")
    return _read(paths[0])


def load_phase_48_6_bundle(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = _one(root, "summary.json")
    plan = _one(root, "plan.json")
    verify_phase_48_6_bundle(summary, plan)
    return summary, plan


def load_phase_48_3_bundle(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        _one(root, "summary.json"),
        _one(root, "plan.json"),
        _one(root, "source-summary.json"),
    )


def verify_phase_48_6_bundle(summary: dict[str, Any], plan: dict[str, Any]) -> None:
    if summary.get("schema") != PHASE_48_6_SUMMARY_SCHEMA:
        raise ValueError("unsupported Phase 48.6 summary")
    if summary.get("status") != "PASS_PARAMETER_STABILITY_EXECUTION_EVIDENCE":
        raise ValueError("Phase 48.6 source is not full execution evidence")
    if summary.get("scope") != "full" or summary.get("stability_passed") is not True:
        raise ValueError("Phase 48.6 source did not pass full parameter stability")
    if summary.get("scenario_count") != 13:
        raise ValueError("Phase 48.6 scenario evidence is incomplete")
    claimed = str(summary.get("report_sha256") or "")
    unsigned = dict(summary)
    unsigned.pop("report_sha256", None)
    if len(claimed) != 64 or _sha(unsigned) != claimed:
        raise ValueError("Phase 48.6 report fingerprint is invalid")
    if plan.get("schema") != PHASE_48_6_PLAN_SCHEMA:
        raise ValueError("unsupported Phase 48.6 plan")
    verify_phase_48_6_plan(plan)
    if summary.get("plan_sha256") != plan.get("plan_sha256"):
        raise ValueError("Phase 48.6 summary and plan do not match")
    expected = int(plan["scenario_count"]) * int(plan["ledger_count"])
    if summary.get("evaluation_count") != expected:
        raise ValueError("Phase 48.6 full evaluation evidence is incomplete")


def _source_assets(source_48_2: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["base_asset"]).upper(): item
        for item in verify_phase_48_2_summary(source_48_2)
    }


def verify_source_chain(
    summary_48_6: dict[str, Any],
    plan_48_6: dict[str, Any],
    summary_48_3: dict[str, Any],
    plan_48_3: dict[str, Any],
    source_48_2: dict[str, Any],
) -> None:
    verify_phase_48_6_bundle(summary_48_6, plan_48_6)
    verify_phase_48_3_summary(summary_48_3)
    verify_phase_48_3_plan(plan_48_3, source_48_2)
    verify_phase_48_2_summary(source_48_2)
    if summary_48_3.get("plan_sha256") != plan_48_3.get("plan_sha256"):
        raise ValueError("Phase 48.3 summary and plan do not match")
    evidence = summary_48_3.get("evidence_sha256")
    if plan_48_6.get("source_phase_48_3_evidence_sha256") != evidence:
        raise ValueError("Phase 48.6 plan does not match Phase 48.3 evidence")
    if plan_48_6.get("source_phase_48_2_evidence_fingerprint") != source_48_2.get(
        "evidence_fingerprint"
    ):
        raise ValueError("Phase 48.6 plan does not match Phase 48.2 evidence")
    expected = {
        (
            str(item["base_asset"]).upper(),
            str(item["split"]),
            item.get("walk_forward_window_index"),
        )
        for item in extract_unique_trade_paths(summary_48_3)
    }
    observed = {
        (
            str(item["base_asset"]).upper(),
            str(item["split"]),
            item.get("walk_forward_window_index"),
        )
        for item in plan_48_6["ledgers"]
    }
    if observed != expected:
        raise ValueError("Phase 48.6 ledgers do not match Phase 48.3 observations")
    source_rules = {
        json.dumps(_ready(item.get("strategy_rules")), sort_keys=True)
        for item in _source_assets(source_48_2).values()
    }
    if source_rules != {json.dumps(plan_48_6["baseline_rules"], sort_keys=True)}:
        raise ValueError("Phase 48.6 baseline rules do not match Phase 48.2")


def build_plan(
    summary_48_6: dict[str, Any],
    plan_48_6: dict[str, Any],
    summary_48_3: dict[str, Any],
    plan_48_3: dict[str, Any],
    source_48_2: dict[str, Any],
    *,
    shard_count: int = SHARD_COUNT,
) -> dict[str, Any]:
    verify_source_chain(
        summary_48_6, plan_48_6, summary_48_3, plan_48_3, source_48_2
    )
    if not 1 <= shard_count <= 100:
        raise ValueError("shard_count must be in [1, 100]")
    ledgers = [dict(item) for item in plan_48_6["ledgers"]]
    ledgers.sort(
        key=lambda item: (
            item["base_asset"],
            item["evaluation_start"],
            item["evaluation_end"],
            item["split"],
        )
    )
    evaluations = []
    for index, ledger in enumerate(ledgers):
        identity = {
            "source_phase_48_6_report_sha256": summary_48_6["report_sha256"],
            "ledger_sha256": ledger["ledger_sha256"],
        }
        evaluations.append(
            {
                "evaluation_sha256": _sha(identity),
                "ledger_index": index,
                "shard": index % shard_count,
                **identity,
            }
        )
    thresholds = RegimeTimeThresholds()
    policy = StrategyValidationPolicy()
    output: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "phase": "48.7",
        "mode": "RESEARCH_PAPER_ONLY",
        "source_phase_48_6_report_sha256": summary_48_6["report_sha256"],
        "source_phase_48_6_results_evidence_sha256": summary_48_6[
            "results_evidence_sha256"
        ],
        "source_phase_48_5_report_sha256": summary_48_6[
            "source_phase_48_5_report_sha256"
        ],
        "source_phase_48_3_evidence_sha256": summary_48_3["evidence_sha256"],
        "source_phase_48_2_evidence_fingerprint": source_48_2[
            "evidence_fingerprint"
        ],
        "baseline_rules": dict(plan_48_6["baseline_rules"]),
        "regime_time_thresholds": _ready(asdict(thresholds)),
        "coverage_thresholds": {
            "min_regime_trade_count": policy.min_regime_trade_count,
            "min_qualified_regimes": policy.min_qualified_regimes,
            "min_active_time_cohorts": 4,
        },
        "regime_model": {
            "timeframe": "1d",
            "semantics": "latest fully completed daily candle; no lookahead",
        },
        "ledger_count": len(ledgers),
        "evaluation_count": len(evaluations),
        "shard_count": shard_count,
        "ledgers": ledgers,
        "evaluations": evaluations,
    }
    output["plan_sha256"] = _sha(output)
    return output


def verify_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unsupported Phase 48.7 plan")
    claimed = str(plan.get("plan_sha256") or "")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if len(claimed) != 64 or _sha(unsigned) != claimed:
        raise ValueError("Phase 48.7 plan fingerprint is invalid")
    if len(plan.get("ledgers", [])) != plan.get("ledger_count"):
        raise ValueError("Phase 48.7 ledger count is invalid")
    if len(plan.get("evaluations", [])) != plan.get("evaluation_count"):
        raise ValueError("Phase 48.7 evaluation count is invalid")


def _selected(plan: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    values = list(plan["evaluations"])
    if scope == "full":
        return values
    if scope != "smoke":
        raise ValueError("scope must be smoke or full")
    assets: list[str] = []
    for ledger in plan["ledgers"]:
        base = str(ledger["base_asset"])
        if base not in assets:
            assets.append(base)
        if len(assets) == SMOKE_ASSET_COUNT:
            break
    allowed = set(assets)
    if not allowed:
        raise ValueError("Phase 48.7 smoke has no assets")
    return [
        item
        for item in values
        if str(plan["ledgers"][item["ledger_index"]]["base_asset"]) in allowed
    ]


def run_shard(
    plan: dict[str, Any],
    source_48_2: dict[str, Any],
    *,
    shard: int,
    scope: str,
) -> list[dict[str, Any]]:
    verify_plan(plan)
    if not 0 <= shard < int(plan["shard_count"]):
        raise ValueError("shard is outside the Phase 48.7 plan")
    sources = _source_assets(source_48_2)
    selected = [item for item in _selected(plan, scope) if item["shard"] == shard]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evaluation in selected:
        ledger = plan["ledgers"][evaluation["ledger_index"]]
        grouped[str(ledger["base_asset"])].append(evaluation)
    rules = StrategyRules(
        **{key: Decimal(str(value)) for key, value in plan["baseline_rules"].items()}
    )
    output = []
    for base in sorted(grouped):
        source = sources[base]
        candles, config = _load_locked_asset(source)
        for evaluation in sorted(grouped[base], key=lambda item: item["ledger_index"]):
            ledger = plan["ledgers"][evaluation["ledger_index"]]
            start = _parse_time(ledger["evaluation_start"])
            end = _parse_time(ledger["evaluation_end"])
            segment = _slice_to(candles, end)
            diagnostics = SignalAttritionDiagnostics()
            events: list[BacktestDiagnosticEvent] = []

            def observe(event: BacktestDiagnosticEvent) -> None:
                diagnostics.record(event)
                events.append(event)

            backtest = BacktestEngine(config, rules=rules).run(
                str(source["symbol"]),
                segment,
                evaluation_start=start,
                diagnostic_observer=observe,
            )
            diagnostic_payload = diagnostics.to_payload()
            _validate_diagnostics(diagnostic_payload, backtest)
            timeline = build_daily_regime_timeline(
                str(source["symbol"]), segment["1d"]
            )
            attribution = attribute_regime_evidence(
                events,
                backtest.trades,
                timeline,
                initial_equity=backtest.initial_equity,
            )
            validate_regime_attribution(
                attribution,
                expected_decision_points=int(diagnostic_payload["decision_points"]),
                expected_ready=int(diagnostic_payload["ready_for_risk_review"]),
                expected_entry_rejections=int(diagnostic_payload["entry_rejections"]),
                expected_trades=len(backtest.trades),
                trades=backtest.trades,
            )
            metrics = _metrics(backtest)
            compact = {
                key: metrics[key]
                for key in (
                    "initial_equity",
                    "final_equity",
                    "trade_count",
                    "max_drawdown_percent",
                    "win_rate_percent",
                    "profit_factor",
                    "total_return_percent",
                    "expectancy_pnl",
                )
            }
            result: dict[str, Any] = {
                "schema": RESULT_SCHEMA,
                "plan_sha256": plan["plan_sha256"],
                "evaluation_sha256": evaluation["evaluation_sha256"],
                "ledger_sha256": ledger["ledger_sha256"],
                "ledger_index": evaluation["ledger_index"],
                "base_asset": base,
                "split": ledger["split"],
                "walk_forward_window_index": ledger["walk_forward_window_index"],
                "evaluation_start": ledger["evaluation_start"],
                "evaluation_end": ledger["evaluation_end"],
                "metrics": compact,
                "decision_point_count": diagnostic_payload["decision_points"],
                "regime_attribution": attribution,
            }
            result = _ready(result)
            result["result_sha256"] = _sha(result)
            output.append(result)
    return output


def _load_results(roots: Iterable[Path]) -> list[dict[str, Any]]:
    output = []
    for root in roots:
        for path in sorted(root.rglob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise ValueError("invalid Phase 48.7 result")
                    output.append(item)
    return output


def _thresholds(plan: dict[str, Any]) -> RegimeTimeThresholds:
    values = dict(plan["regime_time_thresholds"])
    return RegimeTimeThresholds(
        min_regime_count=int(values["min_regime_count"]),
        min_time_slice_count=int(values["min_time_slice_count"]),
        min_slices_per_regime=int(values["min_slices_per_regime"]),
        min_regime_relative_score_percent=Decimal(
            values["min_regime_relative_score_percent"]
        ),
        max_regime_spread_percent=Decimal(values["max_regime_spread_percent"]),
        weak_slice_floor_percent=Decimal(values["weak_slice_floor_percent"]),
        min_stable_time_fraction=Decimal(values["min_stable_time_fraction"]),
        max_time_degradation_percent=Decimal(
            values["max_time_degradation_percent"]
        ),
        max_consecutive_weak_slices=int(values["max_consecutive_weak_slices"]),
        max_slices=int(values["max_slices"]),
    )


def _time_cohort(item: dict[str, Any]) -> str:
    if item["split"] == "LOCKED_OOS":
        return "LOCKED_OOS"
    return f"WALK_FORWARD_{int(item['walk_forward_window_index']) + 1}"


def aggregate(
    plan: dict[str, Any],
    *,
    roots: Iterable[Path],
    scope: str,
) -> dict[str, Any]:
    verify_plan(plan)
    expected = {item["evaluation_sha256"] for item in _selected(plan, scope)}
    by_id: dict[str, dict[str, Any]] = {}
    for item in _load_results(roots):
        if item.get("schema") != RESULT_SCHEMA or item.get("plan_sha256") != plan[
            "plan_sha256"
        ]:
            raise ValueError("result does not belong to this Phase 48.7 plan")
        claimed = item.get("result_sha256")
        unsigned = dict(item)
        unsigned.pop("result_sha256", None)
        if claimed != _sha(unsigned):
            raise ValueError("Phase 48.7 result fingerprint is invalid")
        identity = str(item["evaluation_sha256"])
        if identity in by_id and by_id[identity] != item:
            raise ValueError("conflicting Phase 48.7 results")
        by_id[identity] = item
    if set(by_id) != expected:
        raise ValueError(f"expected {len(expected)} results, got {len(by_id)}")
    ordered = sorted(by_id.values(), key=lambda item: item["ledger_index"])

    regime_trades: Counter[str] = Counter()
    regime_pnl: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    cohort_trades: Counter[str] = Counter()
    slices: list[RegimeTimeSlice] = []
    active_ledgers = 0
    for item in ordered:
        trade_count = int(item["metrics"]["trade_count"])
        if trade_count:
            active_ledgers += 1
        cohort_trades[_time_cohort(item)] += trade_count
        performance = item["regime_attribution"]["trade_performance_by_entry_regime"]
        for regime, values in sorted(performance.items()):
            count = int(values["trade_count"])
            if count < 1:
                continue
            contribution = Decimal(str(values["net_pnl_percent_initial_equity"]))
            regime_trades[regime] += count
            regime_pnl[regime] += Decimal(str(values["net_pnl"]))
            start = int(_parse_time(item["evaluation_start"]).timestamp())
            end = int(_parse_time(item["evaluation_end"]).timestamp()) + 1
            slices.append(
                RegimeTimeSlice(
                    slice_id=_sha(
                        {
                            "evaluation_sha256": item["evaluation_sha256"],
                            "regime": regime,
                        }
                    ),
                    series_id=f"{item['base_asset']}|{regime}",
                    regime=regime,
                    start_index=start,
                    end_index=end,
                    score=Decimal("100") + contribution,
                    sample_count=count,
                )
            )

    qualification_error: str | None = None
    stability = None
    try:
        stability = qualify_regime_time_robustness(
            tuple(slices), thresholds=_thresholds(plan)
        )
    except ValueError as exc:
        qualification_error = str(exc)

    coverage = plan["coverage_thresholds"]
    qualified_regimes = sorted(
        regime
        for regime, count in regime_trades.items()
        if count >= int(coverage["min_regime_trade_count"])
    )
    active_cohorts = sorted(key for key, count in cohort_trades.items() if count > 0)
    coverage_passed = (
        len(qualified_regimes) >= int(coverage["min_qualified_regimes"])
        and len(active_cohorts) >= int(coverage["min_active_time_cohorts"])
    )
    robustness_passed = bool(
        stability is not None and stability.passed and coverage_passed
    )
    report: dict[str, Any] = {
        "schema": SUMMARY_SCHEMA,
        "phase": "48.7",
        "mode": "RESEARCH_PAPER_ONLY",
        "status": (
            "PASS_REGIME_TIME_SMOKE"
            if scope == "smoke"
            else "PASS_REGIME_TIME_EXECUTION_EVIDENCE"
        ),
        "scope": scope,
        "source_phase_48_6_report_sha256": plan[
            "source_phase_48_6_report_sha256"
        ],
        "source_phase_48_6_results_evidence_sha256": plan[
            "source_phase_48_6_results_evidence_sha256"
        ],
        "source_phase_48_5_report_sha256": plan["source_phase_48_5_report_sha256"],
        "source_phase_48_3_evidence_sha256": plan[
            "source_phase_48_3_evidence_sha256"
        ],
        "plan_sha256": plan["plan_sha256"],
        "evaluation_count": len(ordered),
        "active_ledger_count": active_ledgers,
        "zero_trade_ledger_count": len(ordered) - active_ledgers,
        "active_ledger_fraction": (
            Decimal(active_ledgers) / Decimal(len(ordered)) if ordered else Decimal("0")
        ),
        "performance_slice_count": len(slices),
        "regime_trade_counts": dict(sorted(regime_trades.items())),
        "regime_net_pnl": dict(sorted(regime_pnl.items())),
        "time_cohort_trade_counts": dict(sorted(cohort_trades.items())),
        "qualified_regimes": qualified_regimes,
        "active_time_cohorts": active_cohorts,
        "coverage_passed": coverage_passed,
        "regime_time_passed": stability.passed if stability is not None else False,
        "robustness_passed": robustness_passed,
        "qualification_error": qualification_error,
        "regime_time": asdict(stability) if stability is not None else None,
        "results_evidence_sha256": _sha(
            [[item["evaluation_sha256"], item["result_sha256"]] for item in ordered]
        ),
        "limitations": (
            "Each unique locked ledger is replayed once; repeated Phase 48.3 labels are not pseudo-replicated.",
            "Regimes use the latest fully completed daily candle and therefore do not use future information.",
            "Zero-trade ledgers are coverage gaps and are excluded from performance scoring rather than treated as flat returns.",
            "Regime-time robustness does not override weak aggregate return evidence or authorize live trading.",
            "Historical cost and market-impact stress remains Phase 48.8.",
        ),
    }
    report = _ready(report)
    report["report_sha256"] = _sha(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--phase-48-6-root", type=Path, required=True)
    plan_parser.add_argument("--phase-48-3-root", type=Path, required=True)
    plan_parser.add_argument("--shards", type=int, default=SHARD_COUNT)
    plan_parser.add_argument("--output", type=Path, required=True)
    shard_parser = commands.add_parser("shard")
    shard_parser.add_argument("--plan", type=Path, required=True)
    shard_parser.add_argument("--phase-48-3-root", type=Path, required=True)
    shard_parser.add_argument("--shard", type=int, required=True)
    shard_parser.add_argument("--scope", choices=("smoke", "full"), required=True)
    shard_parser.add_argument("--output", type=Path, required=True)
    aggregate_parser = commands.add_parser("aggregate")
    aggregate_parser.add_argument("--plan", type=Path, required=True)
    aggregate_parser.add_argument("--result-root", type=Path, required=True)
    aggregate_parser.add_argument("--scope", choices=("smoke", "full"), required=True)
    aggregate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        summary_48_6, plan_48_6 = load_phase_48_6_bundle(args.phase_48_6_root)
        summary_48_3, plan_48_3, source_48_2 = load_phase_48_3_bundle(
            args.phase_48_3_root
        )
        report = build_plan(
            summary_48_6,
            plan_48_6,
            summary_48_3,
            plan_48_3,
            source_48_2,
            shard_count=args.shards,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "plan_sha256": report["plan_sha256"],
                    "evaluations": report["evaluation_count"],
                },
                sort_keys=True,
            )
        )
        return 0
    plan = _read(args.plan)
    if args.command == "shard":
        _, _, source_48_2 = load_phase_48_3_bundle(args.phase_48_3_root)
        results = run_shard(plan, source_48_2, shard=args.shard, scope=args.scope)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in results),
            encoding="utf-8",
        )
        print(json.dumps({"shard": args.shard, "results": len(results)}))
        return 0
    report = aggregate(plan, roots=[args.result_root], scope=args.scope)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "evaluation_count",
                    "robustness_passed",
                    "report_sha256",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
