"""Run Phase 48.5 price-noise and synthetic-path robustness evidence."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from app.backtest.robustness_sampling import maximum_drawdown_percent
from app.backtest.synthetic_robustness import (
    SyntheticPathConfig,
    SyntheticPathModel,
    corrupt_series_for_quality_test,
    generate_price_path,
    inject_relative_noise,
)
from scripts.backtest.run_phase_48_4_robustness import (
    _sha,
    verify_plan as verify_phase_48_4_plan,
    verify_source as verify_phase_48_3_source,
)

SOURCE_SUMMARY_SCHEMA = "phase-48-4-robustness-summary-v1"
PLAN_SCHEMA = "phase-48-5-synthetic-plan-v1"
RESULT_SCHEMA = "phase-48-5-synthetic-result-v1"
SUMMARY_SCHEMA = "phase-48-5-synthetic-summary-v1"
FULL_SCENARIOS = 10_000
SMOKE_SCENARIOS = 100
NOISE_BPS = (5, 10, 25, 50)
SYNTHETIC_MODELS = tuple(SyntheticPathModel)


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


def _percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    if not values:
        raise ValueError("percentile values must be non-empty")
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * fraction)]


def load_source_bundle(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    summaries = sorted(root.rglob("summary.json"))
    plans = sorted(root.rglob("plan.json"))
    source_summaries = sorted(root.rglob("source-summary.json"))
    if len(summaries) != 1 or len(plans) != 1 or len(source_summaries) != 1:
        raise ValueError("expected one Phase 48.4 summary, plan and source summary")
    summary, plan, source = _read(summaries[0]), _read(plans[0]), _read(source_summaries[0])
    verify_source_bundle(summary, plan, source)
    return summary, plan, source


def verify_source_bundle(
    summary: dict[str, Any], plan: dict[str, Any], source: dict[str, Any]
) -> None:
    verify_phase_48_3_source(source)
    verify_phase_48_4_plan(plan, source)
    if summary.get("schema") != SOURCE_SUMMARY_SCHEMA:
        raise ValueError("unsupported Phase 48.4 source summary")
    if summary.get("status") != "PASS_ROBUSTNESS_EXECUTION_EVIDENCE":
        raise ValueError("Phase 48.4 source is not full execution evidence")
    if summary.get("scope") != "full" or summary.get("simulation_count") != 10_000:
        raise ValueError("Phase 48.4 source is not complete 10000-run evidence")
    claimed = str(summary.get("report_sha256") or "")
    unsigned = dict(summary)
    unsigned.pop("report_sha256", None)
    if len(claimed) != 64 or _sha(unsigned) != claimed:
        raise ValueError("Phase 48.4 report fingerprint is invalid")
    if summary.get("plan_sha256") != plan.get("plan_sha256"):
        raise ValueError("Phase 48.4 summary and plan do not match")
    if summary.get("source_phase_48_3_evidence_sha256") != source.get("evidence_sha256"):
        raise ValueError("Phase 48.4 source chain is broken")


def _trade_key(result: dict[str, Any]) -> tuple[str, str, int | None]:
    window = result.get("walk_forward_window_index")
    return (
        str(result["base_asset"]).upper(),
        str(result["split"]),
        int(window) if window is not None else None,
    )


def extract_unique_ledgers(source: dict[str, Any]) -> list[dict[str, Any]]:
    verify_phase_48_3_source(source)
    ledgers: dict[tuple[str, str, int | None], dict[str, Any]] = {}
    for attempt in source["results"]:
        result = attempt.get("result")
        if not isinstance(result, dict):
            raise ValueError("successful Phase 48.3 attempt is missing its result")
        metrics = result.get("metrics")
        trades = metrics.get("trades") if isinstance(metrics, dict) else None
        if not isinstance(trades, list) or not trades:
            continue
        key = _trade_key(result)
        normalized = []
        for expected_index, trade in enumerate(trades, 1):
            if int(trade["trade_index"]) != expected_index:
                raise ValueError(f"non-contiguous source trade ledger: {key}")
            normalized.append(
                {
                    "trade_index": expected_index,
                    "direction": str(trade["direction"]),
                    "entry_price": str(trade["entry_price"]),
                    "exit_price": str(trade["exit_price"]),
                    "quantity": str(trade["quantity"]),
                    "commission": str(trade["commission"]),
                    "funding_cost": str(trade["funding_cost"]),
                    "realized_pnl": str(trade["realized_pnl"]),
                }
            )
        ledger: dict[str, Any] = {
            "base_asset": key[0],
            "split": key[1],
            "walk_forward_window_index": key[2],
            "initial_equity": str(metrics["initial_equity"]),
            "dataset_fingerprint": result["dataset_fingerprint"],
            "strategy_fingerprint": result["strategy_fingerprint"],
            "trades": normalized,
        }
        ledger["ledger_sha256"] = _sha(ledger)
        prior = ledgers.get(key)
        if prior is not None and prior != ledger:
            raise ValueError(f"conflicting repeated source ledger: {key}")
        ledgers[key] = ledger
    if not ledgers:
        raise ValueError("Phase 48.3 source contains no active trade ledgers")
    return sorted(
        ledgers.values(),
        key=lambda item: (
            item["base_asset"],
            item["split"],
            -1 if item["walk_forward_window_index"] is None else item["walk_forward_window_index"],
        ),
    )


def _validate_trade_indices(values: tuple[int, ...]) -> None:
    if not values or values != tuple(range(1, len(values) + 1)):
        raise ValueError("trade ledger is missing, duplicated or out of order")


def verify_quality_gates(ledgers: list[dict[str, Any]]) -> dict[str, int]:
    original_pass = duplicate_rejected = missing_rejected = 0
    for ledger in ledgers:
        indices = tuple(int(item["trade_index"]) for item in ledger["trades"])
        _validate_trade_indices(indices)
        original_pass += 1
        for kind in ("duplicate", "missing"):
            corrupted = corrupt_series_for_quality_test(
                tuple(Decimal(value) for value in indices),
                duplicate_index=0 if kind == "duplicate" else None,
                remove_index=0 if kind == "missing" else None,
            )
            try:
                _validate_trade_indices(tuple(int(value) for value in corrupted))
            except ValueError:
                if kind == "duplicate":
                    duplicate_rejected += 1
                else:
                    missing_rejected += 1
            else:
                raise ValueError(f"{kind} corruption was not rejected")
    return {
        "original_ledger_pass_count": original_pass,
        "duplicate_corruption_rejected_count": duplicate_rejected,
        "missing_corruption_rejected_count": missing_rejected,
    }


def build_plan(
    summary: dict[str, Any],
    plan_48_4: dict[str, Any],
    source: dict[str, Any],
    *,
    scenario_count: int = FULL_SCENARIOS,
    shard_count: int = 10,
) -> dict[str, Any]:
    verify_source_bundle(summary, plan_48_4, source)
    if scenario_count < 8 or shard_count < 1:
        raise ValueError("scenario_count must cover all modes and shards must be positive")
    ledgers = extract_unique_ledgers(source)
    quality = verify_quality_gates(ledgers)
    modes = [f"PRICE_NOISE_{bps}_BPS" for bps in NOISE_BPS] + [
        f"SYNTHETIC_{model.value}" for model in SYNTHETIC_MODELS
    ]
    scenarios = []
    for index in range(scenario_count):
        ledger_index = index % len(ledgers)
        mode = modes[(index // len(ledgers)) % len(modes)]
        seed = index // (len(ledgers) * len(modes))
        identity = {
            "ledger_sha256": ledgers[ledger_index]["ledger_sha256"],
            "scenario_mode": mode,
            "seed": seed,
        }
        scenarios.append(
            {
                **identity,
                "scenario_sha256": _sha(identity),
                "index": index,
                "ledger_index": ledger_index,
                "shard": index % shard_count,
            }
        )
    if len({item["scenario_sha256"] for item in scenarios}) != len(scenarios):
        raise ValueError("Phase 48.5 plan contains duplicate scenario identities")
    output: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "phase": "48.5",
        "mode": "RESEARCH_PAPER_ONLY",
        "source_phase_48_4_report_sha256": summary["report_sha256"],
        "source_phase_48_4_results_evidence_sha256": summary["results_evidence_sha256"],
        "source_phase_48_3_evidence_sha256": source["evidence_sha256"],
        "unique_observed_trade_ledger_count": len(ledgers),
        "scenario_count": scenario_count,
        "shard_count": shard_count,
        "quality_gate_outcomes": quality,
        "ledgers": ledgers,
        "scenarios": scenarios,
    }
    output["plan_sha256"] = _sha(output)
    return output


def verify_plan(
    plan: dict[str, Any], summary: dict[str, Any], plan_48_4: dict[str, Any], source: dict[str, Any]
) -> None:
    verify_source_bundle(summary, plan_48_4, source)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unsupported Phase 48.5 plan")
    claimed = str(plan.get("plan_sha256") or "")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if len(claimed) != 64 or _sha(unsigned) != claimed:
        raise ValueError("Phase 48.5 plan fingerprint is invalid")
    if plan.get("source_phase_48_4_report_sha256") != summary.get("report_sha256"):
        raise ValueError("Phase 48.5 plan does not match its source")
    if len(plan.get("scenarios", [])) != plan.get("scenario_count"):
        raise ValueError("Phase 48.5 scenario count is invalid")


def _selected(plan: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    values = list(plan["scenarios"])
    if scope == "full":
        return values
    if scope != "smoke":
        raise ValueError("scope must be smoke or full")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in values:
        grouped.setdefault(item["scenario_mode"], []).append(item)
    selected = []
    modes = sorted(grouped)
    while len(selected) < min(SMOKE_SCENARIOS, len(values)):
        for mode in modes:
            if grouped[mode]:
                selected.append(grouped[mode].pop(0))
                if len(selected) == SMOKE_SCENARIOS:
                    break
    return sorted(selected, key=lambda item: item["index"])


def _noise_result(ledger: dict[str, Any], mode: str, seed: int) -> dict[str, Any]:
    bps = int(mode.removeprefix("PRICE_NOISE_").removesuffix("_BPS"))
    pnl = []
    for offset, trade in enumerate(ledger["trades"]):
        entry, exit_price = inject_relative_noise(
            (Decimal(trade["entry_price"]), Decimal(trade["exit_price"])),
            maximum_absolute_percent=Decimal(bps) / Decimal("100"),
            seed=seed * 100_000 + offset,
        )
        quantity = Decimal(trade["quantity"])
        gross = (exit_price - entry) * quantity
        if trade["direction"] == "SHORT":
            gross = -gross
        elif trade["direction"] != "LONG":
            raise ValueError("unsupported trade direction")
        pnl.append(gross - Decimal(trade["commission"]) - Decimal(trade["funding_cost"]))
    initial = Decimal(ledger["initial_equity"])
    final = initial + sum(pnl, Decimal("0"))
    return {
        "scenario_kind": "OBSERVED_TRADE_PRICE_NOISE",
        "noise_bps": bps,
        "trade_count": len(pnl),
        "return_percent": (final - initial) / initial * Decimal("100"),
        "max_drawdown_percent": maximum_drawdown_percent(tuple(pnl), initial_equity=initial),
        "ruin": final <= 0,
        "perturbed_pnl_sha256": _sha(pnl),
    }


def _synthetic_result(ledger: dict[str, Any], mode: str, seed: int) -> dict[str, Any]:
    model = SyntheticPathModel(mode.removeprefix("SYNTHETIC_"))
    returns = [
        math.log(float(Decimal(item["exit_price"]) / Decimal(item["entry_price"])))
        for item in ledger["trades"]
    ]
    drift = max(-0.02, min(0.02, statistics.fmean(returns)))
    volatility = statistics.pstdev(returns) if len(returns) > 1 else 0.02
    volatility = max(0.002, min(0.10, volatility))
    steps = max(100, len(returns) * 5)
    prices = generate_price_path(
        Decimal("100"),
        model=model,
        config=SyntheticPathConfig(
            steps=steps,
            seed=seed,
            drift=Decimal(str(drift)),
            volatility=Decimal(str(volatility)),
        ),
    )
    increments = tuple(prices[index] - prices[index - 1] for index in range(1, len(prices)))
    return {
        "scenario_kind": "SYNTHETIC_MARKET_PATH_DIAGNOSTIC",
        "synthetic_model": model.value,
        "steps": steps,
        "calibrated_drift": Decimal(str(drift)),
        "calibrated_volatility": Decimal(str(volatility)),
        "path_return_percent": (prices[-1] - prices[0]) / prices[0] * Decimal("100"),
        "path_max_drawdown_percent": maximum_drawdown_percent(increments, initial_equity=prices[0]),
        "path_sha256": _sha(prices),
    }


def run_shard(
    plan: dict[str, Any],
    summary: dict[str, Any],
    plan_48_4: dict[str, Any],
    source: dict[str, Any],
    *,
    shard: int,
    scope: str,
) -> list[dict[str, Any]]:
    verify_plan(plan, summary, plan_48_4, source)
    results = []
    for scenario in _selected(plan, scope):
        if scenario["shard"] != shard:
            continue
        ledger = plan["ledgers"][scenario["ledger_index"]]
        mode = scenario["scenario_mode"]
        metrics = (
            _noise_result(ledger, mode, int(scenario["seed"]))
            if mode.startswith("PRICE_NOISE_")
            else _synthetic_result(ledger, mode, int(scenario["seed"]))
        )
        result: dict[str, Any] = {
            "schema": RESULT_SCHEMA,
            "plan_sha256": plan["plan_sha256"],
            "scenario_sha256": scenario["scenario_sha256"],
            "scenario_index": scenario["index"],
            "scenario_mode": mode,
            "seed": scenario["seed"],
            "base_asset": ledger["base_asset"],
            "split": ledger["split"],
            "walk_forward_window_index": ledger["walk_forward_window_index"],
            "ledger_sha256": ledger["ledger_sha256"],
            **metrics,
        }
        result["result_sha256"] = _sha(result)
        results.append(_ready(result))
    return results


def _load_results(roots: Iterable[Path]) -> list[dict[str, Any]]:
    output = []
    for root in roots:
        for path in sorted(root.rglob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise ValueError("invalid Phase 48.5 result")
                    output.append(item)
    return output


def aggregate(
    plan: dict[str, Any],
    summary: dict[str, Any],
    plan_48_4: dict[str, Any],
    source: dict[str, Any],
    *,
    roots: Iterable[Path],
    scope: str,
) -> dict[str, Any]:
    verify_plan(plan, summary, plan_48_4, source)
    expected = {item["scenario_sha256"] for item in _selected(plan, scope)}
    by_id: dict[str, dict[str, Any]] = {}
    for item in _load_results(roots):
        if item.get("schema") != RESULT_SCHEMA or item.get("plan_sha256") != plan["plan_sha256"]:
            raise ValueError("result does not belong to this Phase 48.5 plan")
        claimed = item.get("result_sha256")
        unsigned = dict(item)
        unsigned.pop("result_sha256", None)
        if claimed != _sha(unsigned):
            raise ValueError("Phase 48.5 result fingerprint is invalid")
        identity = item["scenario_sha256"]
        if identity in by_id and by_id[identity] != item:
            raise ValueError("conflicting Phase 48.5 results")
        by_id[identity] = item
    if set(by_id) != expected:
        raise ValueError(f"expected {len(expected)} results, got {len(by_id)}")
    ordered = sorted(by_id.values(), key=lambda item: item["scenario_index"])
    noise = [item for item in ordered if item["scenario_kind"] == "OBSERVED_TRADE_PRICE_NOISE"]
    synthetic = [item for item in ordered if item["scenario_kind"] == "SYNTHETIC_MARKET_PATH_DIAGNOSTIC"]
    noise_returns = [Decimal(item["return_percent"]) for item in noise]
    noise_drawdowns = [Decimal(item["max_drawdown_percent"]) for item in noise]
    path_returns = [Decimal(item["path_return_percent"]) for item in synthetic]
    path_drawdowns = [Decimal(item["path_max_drawdown_percent"]) for item in synthetic]
    report: dict[str, Any] = {
        "schema": SUMMARY_SCHEMA,
        "phase": "48.5",
        "mode": "RESEARCH_PAPER_ONLY",
        "status": "PASS_SYNTHETIC_ROBUSTNESS_SMOKE" if scope == "smoke" else "PASS_SYNTHETIC_ROBUSTNESS_EXECUTION_EVIDENCE",
        "scope": scope,
        "source_phase_48_4_report_sha256": summary["report_sha256"],
        "source_phase_48_4_results_evidence_sha256": summary["results_evidence_sha256"],
        "source_phase_48_3_evidence_sha256": source["evidence_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "unique_observed_trade_ledger_count": plan["unique_observed_trade_ledger_count"],
        "scenario_count": len(ordered),
        "scenario_mode_counts": dict(sorted(Counter(item["scenario_mode"] for item in ordered).items())),
        "quality_gate_outcomes": plan["quality_gate_outcomes"],
        "price_noise_scenario_count": len(noise),
        "price_noise_negative_return_count": sum(value < 0 for value in noise_returns),
        "price_noise_ruin_count": sum(bool(item["ruin"]) for item in noise),
        "price_noise_return_percent_p05": _percentile(noise_returns, Decimal("0.05")),
        "price_noise_return_percent_median": _percentile(noise_returns, Decimal("0.50")),
        "price_noise_return_percent_p95": _percentile(noise_returns, Decimal("0.95")),
        "price_noise_max_drawdown_percent_p95": _percentile(noise_drawdowns, Decimal("0.95")),
        "synthetic_path_scenario_count": len(synthetic),
        "synthetic_path_return_percent_p05": _percentile(path_returns, Decimal("0.05")),
        "synthetic_path_return_percent_median": _percentile(path_returns, Decimal("0.50")),
        "synthetic_path_return_percent_p95": _percentile(path_returns, Decimal("0.95")),
        "synthetic_path_max_drawdown_percent_p95": _percentile(path_drawdowns, Decimal("0.95")),
        "results_evidence_sha256": _sha([[item["scenario_sha256"], item["result_sha256"]] for item in ordered]),
        "limitations": (
            "Price-noise scenarios perturb observed trade entry/exit prices and do not regenerate signals.",
            "Synthetic market paths are diagnostics and are not labelled as strategy returns.",
            "No synthetic result replaces locked OOS or provider-backed historical evidence.",
            "This phase is execution evidence, not final statistical qualification.",
        ),
    }
    report["report_sha256"] = _sha(report)
    return _ready(report)


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--source-root", type=Path, required=True)
    plan_parser.add_argument("--output", type=Path, required=True)
    plan_parser.add_argument("--scenarios", type=int, default=FULL_SCENARIOS)
    plan_parser.add_argument("--shards", type=int, default=10)
    shard_parser = commands.add_parser("shard")
    shard_parser.add_argument("--bundle-root", type=Path, required=True)
    shard_parser.add_argument("--plan", type=Path, required=True)
    shard_parser.add_argument("--shard", type=int, required=True)
    shard_parser.add_argument("--scope", choices=("smoke", "full"), required=True)
    shard_parser.add_argument("--output", type=Path, required=True)
    aggregate_parser = commands.add_parser("aggregate")
    aggregate_parser.add_argument("--bundle-root", type=Path, required=True)
    aggregate_parser.add_argument("--plan", type=Path, required=True)
    aggregate_parser.add_argument("--result-root", type=Path, required=True)
    aggregate_parser.add_argument("--scope", choices=("smoke", "full"), required=True)
    aggregate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        summary, plan_48_4, source = load_source_bundle(args.source_root)
        report = build_plan(summary, plan_48_4, source, scenario_count=args.scenarios, shard_count=args.shards)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"plan_sha256": report["plan_sha256"], "scenarios": report["scenario_count"]}, sort_keys=True))
        return 0
    summary, plan_48_4, source = load_source_bundle(args.bundle_root)
    plan = _read(args.plan)
    if args.command == "shard":
        results = run_shard(plan, summary, plan_48_4, source, shard=args.shard, scope=args.scope)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in results), encoding="utf-8")
        print(json.dumps({"shard": args.shard, "results": len(results)}, sort_keys=True))
        return 0
    report = aggregate(plan, summary, plan_48_4, source, roots=[args.result_root], scope=args.scope)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "scenario_count", "report_sha256")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
