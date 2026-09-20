"""Run real trade-path bootstrap and Monte Carlo from sealed Phase 48.3 evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from app.backtest.robustness_sampling import (
    SamplingMode,
    maximum_drawdown_percent,
    sample_pnl_path,
)

SOURCE_SCHEMA = "phase-48-3-real-matrix-summary-v1"
PLAN_SCHEMA = "phase-48-4-robustness-plan-v1"
RESULT_SCHEMA = "phase-48-4-robustness-result-v1"
SUMMARY_SCHEMA = "phase-48-4-robustness-summary-v1"
FULL_SIMULATIONS = 10_000
SMOKE_SIMULATIONS = 100
DETERMINISTIC_MODES = (
    SamplingMode.REVERSE,
    SamplingMode.WORST_FIRST,
    SamplingMode.LOSS_CLUSTER,
    SamplingMode.WIN_CLUSTER,
)
STOCHASTIC_MODES = (
    SamplingMode.RANDOM_PERMUTATION,
    SamplingMode.IID_BOOTSTRAP,
    SamplingMode.BLOCK_BOOTSTRAP,
)


def _ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_ready(item) for item in value]
    return value


def _canonical(payload: object) -> bytes:
    return json.dumps(
        _ready(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _sha(payload: object) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def verify_source(source: dict[str, Any]) -> None:
    if source.get("schema") != SOURCE_SCHEMA:
        raise ValueError("unsupported Phase 48.3 source schema")
    if source.get("status") != "PASS_1000_RUN_EXECUTION_EVIDENCE":
        raise ValueError("Phase 48.3 source is not full PASS evidence")
    if source.get("expected_runs") != 1000 or source.get("completed_runs") != 1000:
        raise ValueError("Phase 48.3 source is not complete 1000/1000 evidence")
    if source.get("failed_runs") != 0:
        raise ValueError("Phase 48.3 source contains failed runs")
    claimed = str(source.get("report_sha256") or "")
    unsigned = dict(source)
    unsigned.pop("report_sha256", None)
    if len(claimed) != 64 or _sha(unsigned) != claimed:
        raise ValueError("Phase 48.3 report fingerprint is invalid")
    results = source.get("results")
    if not isinstance(results, list) or len(results) != 1000:
        raise ValueError("Phase 48.3 result evidence is incomplete")
    evidence = [
        {
            "experiment_sha256": item["experiment_sha256"],
            "workflow_run_id": item["workflow_run_id"],
            "workflow_attempt": item["workflow_attempt"],
            "status": item["status"],
            "result_sha256": item["result_sha256"],
            "error": item["error"],
        }
        for item in results
    ]
    if _sha(evidence) != source.get("evidence_sha256"):
        raise ValueError("Phase 48.3 evidence fingerprint is invalid")


def extract_unique_trade_paths(source: dict[str, Any]) -> list[dict[str, Any]]:
    verify_source(source)
    paths: dict[tuple[str, str, int | None], dict[str, Any]] = {}
    zero_trade_semantics: set[tuple[str, str, int | None]] = set()
    for attempt in source["results"]:
        result = attempt.get("result")
        if not isinstance(result, dict):
            raise ValueError("successful Phase 48.3 attempt is missing its result")
        metrics = result.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError("Phase 48.3 result is missing metrics")
        trades = metrics.get("trades")
        if not isinstance(trades, list):
            raise ValueError("Phase 48.3 result is missing trades")
        window = result.get("walk_forward_window_index")
        key = (
            str(result["base_asset"]).upper(),
            str(result["split"]),
            int(window) if window is not None else None,
        )
        if not trades:
            zero_trade_semantics.add(key)
            continue
        pnl = tuple(str(item["realized_pnl"]) for item in trades)
        path = {
            "base_asset": key[0],
            "split": key[1],
            "walk_forward_window_index": key[2],
            "initial_equity": str(metrics["initial_equity"]),
            "trade_count": len(pnl),
            "pnl": list(pnl),
            "dataset_fingerprint": result["dataset_fingerprint"],
            "strategy_fingerprint": result["strategy_fingerprint"],
            "config_fingerprint": result["config_fingerprint"],
        }
        path["path_sha256"] = _sha(path)
        prior = paths.get(key)
        if prior is not None and prior != path:
            raise ValueError(f"conflicting repeated trade path: {key}")
        paths[key] = path
    if not paths:
        raise ValueError("Phase 48.3 contains no observed trade paths")
    output = sorted(
        paths.values(),
        key=lambda item: (
            item["base_asset"],
            item["split"],
            -1 if item["walk_forward_window_index"] is None else item["walk_forward_window_index"],
        ),
    )
    return output


def build_plan(
    source: dict[str, Any], *, simulation_count: int = FULL_SIMULATIONS, shard_count: int = 10
) -> dict[str, Any]:
    if simulation_count < 1 or shard_count < 1:
        raise ValueError("simulation_count and shard_count must be positive")
    paths = extract_unique_trade_paths(source)
    simulations: list[dict[str, Any]] = []
    for path_index, path in enumerate(paths):
        for mode in DETERMINISTIC_MODES:
            simulations.append(
                _simulation(path, path_index, mode, seed=0, shard_count=shard_count)
            )
    if len(simulations) > simulation_count:
        raise ValueError("simulation_count cannot cover required adverse paths")
    counters: Counter[tuple[int, SamplingMode]] = Counter()
    index = 0
    while len(simulations) < simulation_count:
        path_index = index % len(paths)
        mode = STOCHASTIC_MODES[(index // len(paths)) % len(STOCHASTIC_MODES)]
        key = (path_index, mode)
        seed = counters[key]
        counters[key] += 1
        simulations.append(
            _simulation(paths[path_index], path_index, mode, seed, shard_count)
        )
        index += 1
    for index, item in enumerate(simulations):
        item["index"] = index
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "phase": "48.4",
        "mode": "RESEARCH_PAPER_ONLY",
        "source_phase_48_3_report_sha256": source["report_sha256"],
        "source_phase_48_3_evidence_sha256": source["evidence_sha256"],
        "unique_observed_trade_path_count": len(paths),
        "simulation_count": simulation_count,
        "shard_count": shard_count,
        "paths": paths,
        "simulations": simulations,
    }
    plan["plan_sha256"] = _sha(plan)
    return plan


def _simulation(
    path: dict[str, Any],
    path_index: int,
    mode: SamplingMode,
    seed: int,
    shard_count: int,
) -> dict[str, Any]:
    identity = {
        "path_sha256": path["path_sha256"],
        "sampling_mode": mode.value,
        "seed": seed,
        "block_size": min(5, int(path["trade_count"])),
    }
    return {
        **identity,
        "simulation_sha256": _sha(identity),
        "path_index": path_index,
        "shard": path_index % shard_count,
    }


def verify_plan(plan: dict[str, Any], source: dict[str, Any]) -> None:
    verify_source(source)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unsupported Phase 48.4 plan")
    claimed = str(plan.get("plan_sha256") or "")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if len(claimed) != 64 or _sha(unsigned) != claimed:
        raise ValueError("Phase 48.4 plan fingerprint is invalid")
    if plan.get("source_phase_48_3_report_sha256") != source.get("report_sha256"):
        raise ValueError("Phase 48.4 plan does not match its source")
    simulations = plan.get("simulations")
    if not isinstance(simulations, list) or len(simulations) != plan.get("simulation_count"):
        raise ValueError("Phase 48.4 simulation count is invalid")
    identities = [item["simulation_sha256"] for item in simulations]
    if len(identities) != len(set(identities)):
        raise ValueError("Phase 48.4 contains duplicate simulation identities")


def _selected(plan: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    simulations = list(plan["simulations"])
    if scope == "full":
        return simulations
    if scope != "smoke":
        raise ValueError("scope must be smoke or full")
    grouped = {mode.value: [] for mode in SamplingMode}
    for item in simulations:
        grouped[item["sampling_mode"]].append(item)
    selected: list[dict[str, Any]] = []
    while len(selected) < min(SMOKE_SIMULATIONS, len(simulations)):
        changed = False
        for mode in SamplingMode:
            values = grouped[mode.value]
            if values:
                selected.append(values.pop(0))
                changed = True
                if len(selected) == SMOKE_SIMULATIONS:
                    break
        if not changed:
            break
    return sorted(selected, key=lambda item: item["index"])


def run_shard(plan: dict[str, Any], source: dict[str, Any], *, shard: int, scope: str) -> list[dict[str, Any]]:
    verify_plan(plan, source)
    paths = plan["paths"]
    selected = [item for item in _selected(plan, scope) if item["shard"] == shard]
    results = []
    for simulation in selected:
        path = paths[simulation["path_index"]]
        pnl = tuple(Decimal(value) for value in path["pnl"])
        initial = Decimal(path["initial_equity"])
        sampled = sample_pnl_path(
            pnl,
            mode=SamplingMode(simulation["sampling_mode"]),
            seed=int(simulation["seed"]),
            block_size=int(simulation["block_size"]),
        )
        final = initial + sum(sampled, Decimal("0"))
        result = {
            "schema": RESULT_SCHEMA,
            "plan_sha256": plan["plan_sha256"],
            "simulation_sha256": simulation["simulation_sha256"],
            "simulation_index": simulation["index"],
            "base_asset": path["base_asset"],
            "split": path["split"],
            "walk_forward_window_index": path["walk_forward_window_index"],
            "path_sha256": path["path_sha256"],
            "sampling_mode": simulation["sampling_mode"],
            "seed": simulation["seed"],
            "trade_count": len(sampled),
            "initial_equity": initial,
            "final_equity": final,
            "return_percent": (final - initial) / initial * Decimal("100"),
            "mean_trade_pnl": sum(sampled, Decimal("0")) / len(sampled),
            "max_drawdown_percent": maximum_drawdown_percent(
                sampled, initial_equity=initial
            ),
            "ruin": final <= 0,
            "sampled_pnl_sha256": _sha(sampled),
        }
        result["result_sha256"] = _sha(result)
        results.append(_ready(result))
    return results


def _percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    if not values:
        raise ValueError("percentile values must be non-empty")
    ordered = sorted(values)
    index = int((len(ordered) - 1) * fraction)
    return ordered[index]


def _load_results(roots: Iterable[Path]) -> list[dict[str, Any]]:
    output = []
    for root in roots:
        for path in sorted(root.rglob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise ValueError("invalid robustness result")
                    output.append(item)
    return output


def aggregate(plan: dict[str, Any], source: dict[str, Any], *, roots: Iterable[Path], scope: str) -> dict[str, Any]:
    verify_plan(plan, source)
    expected = {item["simulation_sha256"] for item in _selected(plan, scope)}
    results = _load_results(roots)
    by_id: dict[str, dict[str, Any]] = {}
    for item in results:
        if item.get("schema") != RESULT_SCHEMA or item.get("plan_sha256") != plan["plan_sha256"]:
            raise ValueError("result does not belong to this Phase 48.4 plan")
        claimed = item.get("result_sha256")
        unsigned = dict(item)
        unsigned.pop("result_sha256", None)
        if claimed != _sha(unsigned):
            raise ValueError("Phase 48.4 result fingerprint is invalid")
        identity = item["simulation_sha256"]
        if identity in by_id and by_id[identity] != item:
            raise ValueError("conflicting Phase 48.4 results")
        by_id[identity] = item
    if set(by_id) != expected:
        raise ValueError(f"expected {len(expected)} results, got {len(by_id)}")
    ordered = sorted(by_id.values(), key=lambda item: item["simulation_index"])
    returns = [Decimal(item["return_percent"]) for item in ordered]
    drawdowns = [Decimal(item["max_drawdown_percent"]) for item in ordered]
    expectancies = [Decimal(item["mean_trade_pnl"]) for item in ordered]
    modes = Counter(item["sampling_mode"] for item in ordered)
    report: dict[str, Any] = {
        "schema": SUMMARY_SCHEMA,
        "phase": "48.4",
        "mode": "RESEARCH_PAPER_ONLY",
        "status": "PASS_ROBUSTNESS_SMOKE" if scope == "smoke" else "PASS_ROBUSTNESS_EXECUTION_EVIDENCE",
        "scope": scope,
        "source_phase_48_3_report_sha256": source["report_sha256"],
        "source_phase_48_3_evidence_sha256": source["evidence_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "unique_observed_trade_path_count": plan["unique_observed_trade_path_count"],
        "simulation_count": len(ordered),
        "sampling_mode_counts": dict(sorted(modes.items())),
        "positive_return_count": sum(value > 0 for value in returns),
        "negative_return_count": sum(value < 0 for value in returns),
        "zero_return_count": sum(value == 0 for value in returns),
        "ruin_count": sum(bool(item["ruin"]) for item in ordered),
        "return_percent_p05": _percentile(returns, Decimal("0.05")),
        "return_percent_median": _percentile(returns, Decimal("0.50")),
        "return_percent_p95": _percentile(returns, Decimal("0.95")),
        "max_drawdown_percent_median": _percentile(drawdowns, Decimal("0.50")),
        "max_drawdown_percent_p95": _percentile(drawdowns, Decimal("0.95")),
        "max_drawdown_percent_p99": _percentile(drawdowns, Decimal("0.99")),
        "mean_trade_pnl_p025": _percentile(expectancies, Decimal("0.025")),
        "mean_trade_pnl_median": _percentile(expectancies, Decimal("0.50")),
        "mean_trade_pnl_p975": _percentile(expectancies, Decimal("0.975")),
        "results_evidence_sha256": _sha(
            [[item["simulation_sha256"], item["result_sha256"]] for item in ordered]
        ),
        "limitations": (
            "Bootstrap paths resample observed net trade PnL and do not create new market history.",
            "Repeated Phase 48.3 evaluations are collapsed to unique asset/split/window trade paths.",
            "This phase is robustness evidence, not final statistical qualification.",
        ),
    }
    report["report_sha256"] = _sha(report)
    return _ready(report)


def _find_summary(root: Path) -> Path:
    values = sorted(root.rglob("summary.json"))
    if len(values) != 1:
        raise ValueError(f"expected one summary.json, got {len(values)}")
    return values[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--source-root", type=Path, required=True)
    plan_parser.add_argument("--output", type=Path, required=True)
    plan_parser.add_argument("--simulations", type=int, default=FULL_SIMULATIONS)
    plan_parser.add_argument("--shards", type=int, default=10)
    shard_parser = commands.add_parser("shard")
    shard_parser.add_argument("--plan", type=Path, required=True)
    shard_parser.add_argument("--source", type=Path, required=True)
    shard_parser.add_argument("--shard", type=int, required=True)
    shard_parser.add_argument("--scope", choices=("smoke", "full"), required=True)
    shard_parser.add_argument("--output", type=Path, required=True)
    aggregate_parser = commands.add_parser("aggregate")
    aggregate_parser.add_argument("--plan", type=Path, required=True)
    aggregate_parser.add_argument("--source", type=Path, required=True)
    aggregate_parser.add_argument("--result-root", type=Path, required=True)
    aggregate_parser.add_argument("--scope", choices=("smoke", "full"), required=True)
    aggregate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        source_path = _find_summary(args.source_root)
        source = _read(source_path)
        report = build_plan(source, simulation_count=args.simulations, shard_count=args.shards)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"plan_sha256": report["plan_sha256"], "simulations": report["simulation_count"]}))
        return 0
    plan = _read(args.plan)
    source = _read(args.source)
    if args.command == "shard":
        results = run_shard(plan, source, shard=args.shard, scope=args.scope)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in results))
        print(json.dumps({"shard": args.shard, "results": len(results)}))
        return 0
    report = aggregate(plan, source, roots=[args.result_root], scope=args.scope)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "simulation_count", "report_sha256")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
