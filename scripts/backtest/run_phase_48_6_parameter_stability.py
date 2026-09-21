"""Run real Phase 48.6 one-at-a-time parameter sensitivity evidence.

The executor verifies the complete Phase 48.5 -> 48.3 -> 48.2 chain, then
replays the locked OOS and walk-forward evaluations with bounded changes to the
three strategy acceptance thresholds.  Costs, data, splits and risk settings
remain frozen.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from app.backtest.engine import BacktestEngine
from app.backtest.parameter_stability import (
    ParameterSweepSpec,
    PerturbationMode,
    StabilityThresholds,
    qualify_parameter_stability,
)
from app.strategy.rules import StrategyRules
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

PHASE_48_5_SUMMARY_SCHEMA = "phase-48-5-synthetic-summary-v1"
PHASE_48_5_PLAN_SCHEMA = "phase-48-5-synthetic-plan-v1"
PLAN_SCHEMA = "phase-48-6-parameter-plan-v1"
RESULT_SCHEMA = "phase-48-6-parameter-result-v1"
SUMMARY_SCHEMA = "phase-48-6-parameter-summary-v1"
SMOKE_ASSET_COUNT = 8
SHARD_COUNT = 10


def _ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
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


def load_phase_48_5_bundle(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = _one(root, "summary.json")
    plan = _one(root, "plan.json")
    verify_phase_48_5_bundle(summary, plan)
    return summary, plan


def load_phase_48_3_bundle(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    summary = _one(root, "summary.json")
    plan = _one(root, "plan.json")
    source = _one(root, "source-summary.json")
    return summary, plan, source


def verify_phase_48_5_bundle(summary: dict[str, Any], plan: dict[str, Any]) -> None:
    if summary.get("schema") != PHASE_48_5_SUMMARY_SCHEMA:
        raise ValueError("unsupported Phase 48.5 summary")
    if summary.get("status") != "PASS_SYNTHETIC_ROBUSTNESS_EXECUTION_EVIDENCE":
        raise ValueError("Phase 48.5 source is not full execution evidence")
    if summary.get("scope") != "full" or summary.get("scenario_count") != 10_000:
        raise ValueError("Phase 48.5 source is not complete 10000-scenario evidence")
    claimed = str(summary.get("report_sha256") or "")
    unsigned = dict(summary)
    unsigned.pop("report_sha256", None)
    if len(claimed) != 64 or _sha(unsigned) != claimed:
        raise ValueError("Phase 48.5 report fingerprint is invalid")
    if plan.get("schema") != PHASE_48_5_PLAN_SCHEMA:
        raise ValueError("unsupported Phase 48.5 plan")
    plan_claimed = str(plan.get("plan_sha256") or "")
    plan_unsigned = dict(plan)
    plan_unsigned.pop("plan_sha256", None)
    if len(plan_claimed) != 64 or _sha(plan_unsigned) != plan_claimed:
        raise ValueError("Phase 48.5 plan fingerprint is invalid")
    if summary.get("plan_sha256") != plan_claimed:
        raise ValueError("Phase 48.5 summary and plan do not match")
    if len(plan.get("scenarios", [])) != 10_000:
        raise ValueError("Phase 48.5 plan is incomplete")
    ledgers = plan.get("ledgers")
    if not isinstance(ledgers, list) or len(ledgers) != summary.get(
        "unique_observed_trade_ledger_count"
    ):
        raise ValueError("Phase 48.5 ledger evidence is incomplete")
    for key in (
        "source_phase_48_4_report_sha256",
        "source_phase_48_4_results_evidence_sha256",
        "source_phase_48_3_evidence_sha256",
    ):
        if summary.get(key) != plan.get(key):
            raise ValueError(f"Phase 48.5 source chain mismatch: {key}")


def verify_source_chain(
    summary_48_5: dict[str, Any],
    plan_48_5: dict[str, Any],
    summary_48_3: dict[str, Any],
    plan_48_3: dict[str, Any],
    source_48_2: dict[str, Any],
) -> None:
    verify_phase_48_5_bundle(summary_48_5, plan_48_5)
    verify_phase_48_3_summary(summary_48_3)
    verify_phase_48_3_plan(plan_48_3, source_48_2)
    verify_phase_48_2_summary(source_48_2)
    if summary_48_3.get("plan_sha256") != plan_48_3.get("plan_sha256"):
        raise ValueError("Phase 48.3 summary and plan do not match")
    expected = summary_48_3.get("evidence_sha256")
    if summary_48_5.get("source_phase_48_3_evidence_sha256") != expected:
        raise ValueError("Phase 48.5 summary does not match Phase 48.3 evidence")
    if plan_48_5.get("source_phase_48_3_evidence_sha256") != expected:
        raise ValueError("Phase 48.5 plan does not match Phase 48.3 evidence")
    observed = {
        (
            str(item["base_asset"]).upper(),
            str(item["split"]),
            item.get("walk_forward_window_index"),
        )
        for item in extract_unique_trade_paths(summary_48_3)
    }
    carried = {
        (
            str(item["base_asset"]).upper(),
            str(item["split"]),
            item.get("walk_forward_window_index"),
        )
        for item in plan_48_5["ledgers"]
    }
    if carried != observed:
        raise ValueError("Phase 48.5 ledgers do not match Phase 48.3 observations")


def _specs(rules: StrategyRules) -> tuple[ParameterSweepSpec, ...]:
    return (
        ParameterSweepSpec(
            "min_rr",
            rules.min_rr,
            tuple(Decimal(value) for value in ("-0.50", "-0.25", "0.25", "0.50")),
            mode=PerturbationMode.ABSOLUTE,
            lower_bound=Decimal("1.5"),
            upper_bound=Decimal("4.0"),
        ),
        ParameterSweepSpec(
            "min_score",
            rules.min_score,
            tuple(Decimal(value) for value in ("-10", "-5", "5", "10")),
            mode=PerturbationMode.ABSOLUTE,
            lower_bound=Decimal("0"),
            upper_bound=Decimal("100"),
        ),
        ParameterSweepSpec(
            "min_confidence",
            rules.min_confidence,
            tuple(Decimal(value) for value in ("-10", "-5", "5", "10")),
            mode=PerturbationMode.ABSOLUTE,
            lower_bound=Decimal("0"),
            upper_bound=Decimal("100"),
        ),
    )


def _rules_payload(rules: StrategyRules) -> dict[str, str]:
    return {key: str(value) for key, value in asdict(rules).items()}


def _scenario(
    *,
    rules: StrategyRules,
    parameter: str | None,
    requested_perturbation: Decimal,
    source_report_sha256: str,
) -> dict[str, Any]:
    identity = {
        "parameter": parameter or "BASELINE",
        "requested_perturbation": str(requested_perturbation),
        "rules": _rules_payload(rules),
        "source_phase_48_5_report_sha256": source_report_sha256,
    }
    return {
        **identity,
        "scenario_sha256": _sha(identity),
    }


def _scenario_set(rules: StrategyRules, source_report_sha256: str) -> list[dict[str, Any]]:
    output = [
        _scenario(
            rules=rules,
            parameter=None,
            requested_perturbation=Decimal("0"),
            source_report_sha256=source_report_sha256,
        )
    ]
    baseline = asdict(rules)
    for spec in _specs(rules):
        for perturbation in spec.perturbations:
            value = spec.baseline + perturbation
            if spec.lower_bound is not None:
                value = max(value, spec.lower_bound)
            if spec.upper_bound is not None:
                value = min(value, spec.upper_bound)
            values = dict(baseline)
            values[spec.name] = value
            output.append(
                _scenario(
                    rules=StrategyRules(**values),
                    parameter=spec.name,
                    requested_perturbation=perturbation,
                    source_report_sha256=source_report_sha256,
                )
            )
    if len({item["scenario_sha256"] for item in output}) != len(output):
        raise ValueError("Phase 48.6 scenarios are not unique")
    return output


def _sources(source_48_2: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["base_asset"]).upper(): item
        for item in verify_phase_48_2_summary(source_48_2)
    }


def _boundaries(source: dict[str, Any], ledger: dict[str, Any]) -> tuple[str, str]:
    split = str(ledger["split"])
    if split == "LOCKED_OOS":
        return str(source["split"]["oos_start"]), str(source["split"]["oos_end"])
    if split != "WALK_FORWARD":
        raise ValueError(f"unsupported Phase 48.6 split: {split}")
    index = ledger.get("walk_forward_window_index")
    windows = source.get("walk_forward", {}).get("windows", [])
    if not isinstance(index, int) or not 0 <= index < len(windows):
        raise ValueError("invalid Phase 48.6 walk-forward window")
    return str(windows[index]["test_start"]), str(windows[index]["test_end"])


def build_plan(
    summary_48_5: dict[str, Any],
    plan_48_5: dict[str, Any],
    summary_48_3: dict[str, Any],
    plan_48_3: dict[str, Any],
    source_48_2: dict[str, Any],
    *,
    shard_count: int = SHARD_COUNT,
) -> dict[str, Any]:
    verify_source_chain(
        summary_48_5, plan_48_5, summary_48_3, plan_48_3, source_48_2
    )
    if not 1 <= shard_count <= 100:
        raise ValueError("shard_count must be in [1, 100]")
    sources = _sources(source_48_2)
    ledgers: list[dict[str, Any]] = []
    for raw in plan_48_5["ledgers"]:
        base = str(raw["base_asset"]).upper()
        source = sources.get(base)
        if source is None:
            raise ValueError(f"Phase 48.6 source asset is missing: {base}")
        start, end = _boundaries(source, raw)
        ledger = {
            "base_asset": base,
            "symbol": str(source["symbol"]),
            "split": str(raw["split"]),
            "walk_forward_window_index": raw.get("walk_forward_window_index"),
            "evaluation_start": start,
            "evaluation_end": end,
            "dataset_fingerprint": str(source["dataset_fingerprint"]),
            "config_fingerprint": str(source["config_fingerprint"]),
        }
        ledger["ledger_sha256"] = _sha(ledger)
        ledgers.append(ledger)
    ledgers.sort(
        key=lambda item: (
            item["base_asset"],
            item["split"],
            -1
            if item["walk_forward_window_index"] is None
            else item["walk_forward_window_index"],
        )
    )
    strategy_payloads = {
        json.dumps(_ready(item.get("strategy_rules")), sort_keys=True)
        for item in sources.values()
    }
    if len(strategy_payloads) != 1:
        raise ValueError("Phase 48.2 assets do not share one strategy rule set")
    raw_rules = next(iter(sources.values())).get("strategy_rules")
    if not isinstance(raw_rules, dict):
        raise ValueError("Phase 48.2 source is missing frozen strategy rules")
    rules = StrategyRules(**{key: Decimal(str(value)) for key, value in raw_rules.items()})
    scenarios = _scenario_set(rules, str(summary_48_5["report_sha256"]))
    evaluations: list[dict[str, Any]] = []
    for scenario_index, scenario in enumerate(scenarios):
        for ledger_index, ledger in enumerate(ledgers):
            identity = {
                "scenario_sha256": scenario["scenario_sha256"],
                "ledger_sha256": ledger["ledger_sha256"],
            }
            evaluations.append(
                {
                    **identity,
                    "evaluation_sha256": _sha(identity),
                    "scenario_index": scenario_index,
                    "ledger_index": ledger_index,
                    "shard": ledger_index % shard_count,
                }
            )
    thresholds = StabilityThresholds(
        stability_tolerance_percent=Decimal("0.50"),
        max_degradation_percent=Decimal("1.50"),
        min_stable_fraction=Decimal("0.75"),
        max_adjacent_cliff_percent=Decimal("1.00"),
    )
    output: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "phase": "48.6",
        "mode": "RESEARCH_PAPER_ONLY",
        "source_phase_48_5_report_sha256": summary_48_5["report_sha256"],
        "source_phase_48_5_results_evidence_sha256": summary_48_5[
            "results_evidence_sha256"
        ],
        "source_phase_48_3_evidence_sha256": summary_48_3["evidence_sha256"],
        "source_phase_48_2_evidence_fingerprint": source_48_2[
            "evidence_fingerprint"
        ],
        "baseline_rules": _rules_payload(rules),
        "sweep_specs": _ready([asdict(item) for item in _specs(rules)]),
        "thresholds": _ready(asdict(thresholds)),
        "scenario_count": len(scenarios),
        "ledger_count": len(ledgers),
        "evaluation_count": len(evaluations),
        "shard_count": shard_count,
        "scenarios": scenarios,
        "ledgers": ledgers,
        "evaluations": evaluations,
    }
    output["plan_sha256"] = _sha(output)
    return output


def verify_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unsupported Phase 48.6 plan")
    claimed = str(plan.get("plan_sha256") or "")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if len(claimed) != 64 or _sha(unsigned) != claimed:
        raise ValueError("Phase 48.6 plan fingerprint is invalid")
    if len(plan.get("scenarios", [])) != plan.get("scenario_count"):
        raise ValueError("Phase 48.6 scenario count is invalid")
    if len(plan.get("ledgers", [])) != plan.get("ledger_count"):
        raise ValueError("Phase 48.6 ledger count is invalid")
    if len(plan.get("evaluations", [])) != plan.get("evaluation_count"):
        raise ValueError("Phase 48.6 evaluation count is invalid")


def _selected(plan: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    values = list(plan["evaluations"])
    if scope == "full":
        return values
    if scope != "smoke":
        raise ValueError("scope must be smoke or full")
    ledger_indexes: list[int] = []
    seen_assets: set[str] = set()
    for index, ledger in enumerate(plan["ledgers"]):
        base = str(ledger["base_asset"])
        if base in seen_assets:
            continue
        seen_assets.add(base)
        ledger_indexes.append(index)
        if len(ledger_indexes) == min(SMOKE_ASSET_COUNT, len(seen_assets)):
            if len(ledger_indexes) == SMOKE_ASSET_COUNT:
                break
    if not ledger_indexes:
        raise ValueError("Phase 48.6 smoke has no ledgers")
    allowed = set(ledger_indexes)
    return [item for item in values if int(item["ledger_index"]) in allowed]


def run_shard(
    plan: dict[str, Any],
    source_48_2: dict[str, Any],
    *,
    shard: int,
    scope: str,
) -> list[dict[str, Any]]:
    verify_plan(plan)
    if not 0 <= shard < int(plan["shard_count"]):
        raise ValueError("shard is outside the Phase 48.6 plan")
    sources = _sources(source_48_2)
    selected = [item for item in _selected(plan, scope) if item["shard"] == shard]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evaluation in selected:
        ledger = plan["ledgers"][evaluation["ledger_index"]]
        grouped[str(ledger["base_asset"])].append(evaluation)
    results: list[dict[str, Any]] = []
    for base in sorted(grouped):
        source = sources[base]
        candles, config = _load_locked_asset(source)
        for evaluation in sorted(
            grouped[base], key=lambda item: (item["scenario_index"], item["ledger_index"])
        ):
            ledger = plan["ledgers"][evaluation["ledger_index"]]
            scenario = plan["scenarios"][evaluation["scenario_index"]]
            rules = StrategyRules(
                **{
                    key: Decimal(str(value))
                    for key, value in scenario["rules"].items()
                }
            )
            start = _parse_time(ledger["evaluation_start"])
            end = _parse_time(ledger["evaluation_end"])
            backtest = BacktestEngine(config, rules=rules).run(
                str(source["symbol"]),
                _slice_to(candles, end),
                evaluation_start=start,
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
                "scenario_sha256": scenario["scenario_sha256"],
                "ledger_sha256": ledger["ledger_sha256"],
                "scenario_index": evaluation["scenario_index"],
                "ledger_index": evaluation["ledger_index"],
                "base_asset": base,
                "split": ledger["split"],
                "walk_forward_window_index": ledger["walk_forward_window_index"],
                "parameter": scenario["parameter"],
                "requested_perturbation": scenario["requested_perturbation"],
                "rules": scenario["rules"],
                "metrics": compact,
            }
            result = _ready(result)
            result["result_sha256"] = _sha(result)
            results.append(result)
    return results


def _load_results(roots: Iterable[Path]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for root in roots:
        for path in sorted(root.rglob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise ValueError("invalid Phase 48.6 result")
                    output.append(item)
    return output


def _percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile input is empty")
    return ordered[int((len(ordered) - 1) * fraction)]


def _thresholds(plan: dict[str, Any]) -> StabilityThresholds:
    payload = dict(plan["thresholds"])
    return StabilityThresholds(
        stability_tolerance_percent=Decimal(payload["stability_tolerance_percent"]),
        max_degradation_percent=Decimal(payload["max_degradation_percent"]),
        min_stable_fraction=Decimal(payload["min_stable_fraction"]),
        max_adjacent_cliff_percent=Decimal(payload["max_adjacent_cliff_percent"]),
        max_scenarios=int(payload["max_scenarios"]),
    )


def _sweep_specs(plan: dict[str, Any]) -> tuple[ParameterSweepSpec, ...]:
    output = []
    for item in plan["sweep_specs"]:
        output.append(
            ParameterSweepSpec(
                name=item["name"],
                baseline=Decimal(item["baseline"]),
                perturbations=tuple(Decimal(value) for value in item["perturbations"]),
                mode=PerturbationMode(item["mode"]),
                lower_bound=Decimal(item["lower_bound"])
                if item["lower_bound"] is not None
                else None,
                upper_bound=Decimal(item["upper_bound"])
                if item["upper_bound"] is not None
                else None,
            )
        )
    return tuple(output)


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
            raise ValueError("result does not belong to this Phase 48.6 plan")
        claimed = item.get("result_sha256")
        unsigned = dict(item)
        unsigned.pop("result_sha256", None)
        if claimed != _sha(unsigned):
            raise ValueError("Phase 48.6 result fingerprint is invalid")
        identity = str(item["evaluation_sha256"])
        if identity in by_id and by_id[identity] != item:
            raise ValueError("conflicting Phase 48.6 results")
        by_id[identity] = item
    if set(by_id) != expected:
        raise ValueError(f"expected {len(expected)} results, got {len(by_id)}")
    ordered = sorted(
        by_id.values(), key=lambda item: (item["scenario_index"], item["ledger_index"])
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in ordered:
        grouped[str(item["scenario_sha256"])].append(item)
    scores: dict[tuple[tuple[str, str], ...], Decimal] = {}
    scenario_summaries = []
    for scenario in plan["scenarios"]:
        results = grouped[scenario["scenario_sha256"]]
        final = [Decimal(item["metrics"]["final_equity"]) for item in results]
        returns = [Decimal(item["metrics"]["total_return_percent"]) for item in results]
        drawdowns = [Decimal(item["metrics"]["max_drawdown_percent"]) for item in results]
        score = sum(final, Decimal("0")) / Decimal(len(final))
        key = tuple(sorted((name, str(value)) for name, value in scenario["rules"].items()))
        scores[key] = score
        scenario_summaries.append(
            {
                "scenario_sha256": scenario["scenario_sha256"],
                "parameter": scenario["parameter"],
                "requested_perturbation": scenario["requested_perturbation"],
                "rules": scenario["rules"],
                "evaluation_count": len(results),
                "mean_final_equity_score": score,
                "return_percent_p05": _percentile(returns, Decimal("0.05")),
                "return_percent_median": _percentile(returns, Decimal("0.50")),
                "return_percent_p95": _percentile(returns, Decimal("0.95")),
                "max_drawdown_percent_p95": _percentile(drawdowns, Decimal("0.95")),
                "trade_count": sum(int(item["metrics"]["trade_count"]) for item in results),
            }
        )

    def evaluator(parameters: dict[str, Decimal]) -> Decimal:
        key = tuple(sorted((name, str(value)) for name, value in parameters.items()))
        try:
            return scores[key]
        except KeyError as exc:
            raise ValueError(f"missing evaluated parameter scenario: {parameters}") from exc

    stability = qualify_parameter_stability(
        _sweep_specs(plan), evaluator=evaluator, thresholds=_thresholds(plan)
    )
    report: dict[str, Any] = {
        "schema": SUMMARY_SCHEMA,
        "phase": "48.6",
        "mode": "RESEARCH_PAPER_ONLY",
        "status": "PASS_PARAMETER_STABILITY_SMOKE"
        if scope == "smoke"
        else "PASS_PARAMETER_STABILITY_EXECUTION_EVIDENCE",
        "scope": scope,
        "source_phase_48_5_report_sha256": plan["source_phase_48_5_report_sha256"],
        "source_phase_48_5_results_evidence_sha256": plan[
            "source_phase_48_5_results_evidence_sha256"
        ],
        "source_phase_48_3_evidence_sha256": plan[
            "source_phase_48_3_evidence_sha256"
        ],
        "plan_sha256": plan["plan_sha256"],
        "scenario_count": len(plan["scenarios"]),
        "evaluation_count": len(ordered),
        "parameter_counts": dict(
            sorted(Counter(item["parameter"] for item in plan["scenarios"]).items())
        ),
        "stability_passed": stability.passed,
        "stability": asdict(stability),
        "scenario_summaries": scenario_summaries,
        "results_evidence_sha256": _sha(
            [[item["evaluation_sha256"], item["result_sha256"]] for item in ordered]
        ),
        "limitations": (
            "One-at-a-time sweeps measure local sensitivity and do not optimize parameters.",
            "Locked OOS and walk-forward boundaries, datasets, costs and risk settings remain unchanged.",
            "A stability verdict does not override weak return evidence from earlier phases.",
            "This phase is execution evidence, not final statistical qualification.",
        ),
    }
    report = _ready(report)
    report["report_sha256"] = _sha(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--phase-48-5-root", type=Path, required=True)
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
        summary_48_5, plan_48_5 = load_phase_48_5_bundle(args.phase_48_5_root)
        summary_48_3, plan_48_3, source_48_2 = load_phase_48_3_bundle(
            args.phase_48_3_root
        )
        report = build_plan(
            summary_48_5,
            plan_48_5,
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
                    "scenarios": report["scenario_count"],
                    "evaluations": report["evaluation_count"],
                },
                sort_keys=True,
            )
        )
        return 0
    plan = _read(args.plan)
    if args.command == "shard":
        _, _, source_48_2 = load_phase_48_3_bundle(args.phase_48_3_root)
        results = run_shard(
            plan, source_48_2, shard=args.shard, scope=args.scope
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in results),
            encoding="utf-8",
        )
        print(json.dumps({"shard": args.shard, "results": len(results)}, sort_keys=True))
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
                    "stability_passed",
                    "report_sha256",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
