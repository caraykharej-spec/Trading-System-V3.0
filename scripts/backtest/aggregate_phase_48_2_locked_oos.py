"""Aggregate Phase 48.2 per-asset evidence without inventing pending performance."""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


def _decimal(value: object) -> Decimal:
    return Decimal(str(value if value is not None else "0"))


def aggregate(
    paths: Iterable[Path],
    *,
    expected_assets: int,
    expected_pending: int,
) -> dict[str, Any]:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(paths)]
    if len(reports) != expected_assets:
        raise ValueError(f"expected {expected_assets} asset reports, got {len(reports)}")
    bases = [str(item.get("base_asset") or "").upper() for item in reports]
    if len(set(bases)) != len(bases):
        raise ValueError("duplicate asset reports")
    pending = sorted(
        item["base_asset"]
        for item in reports
        if item.get("execution_status") == "WARMUP_PENDING"
    )
    complete = [
        item for item in reports if item.get("execution_status") == "COMPLETE"
    ]
    unknown = [
        item
        for item in reports
        if item.get("execution_status") not in {"COMPLETE", "WARMUP_PENDING"}
    ]
    if unknown:
        raise ValueError("unsupported execution status in aggregate")
    if len(pending) != expected_pending:
        raise ValueError(
            f"expected {expected_pending} pending assets, got {len(pending)}: {pending}"
        )

    total_trades = sum(
        int(item["locked_oos_metrics"]["trade_count"]) for item in complete
    )
    returns = [
        _decimal(item["locked_oos_metrics"]["total_return_percent"])
        for item in complete
    ]
    drawdowns = [
        _decimal(item["locked_oos_metrics"]["max_drawdown_percent"])
        for item in complete
    ]
    profit_factors = [
        _decimal(item["locked_oos_metrics"]["profit_factor"])
        for item in complete
        if item["locked_oos_metrics"].get("profit_factor") is not None
    ]
    expectancies = [
        _decimal(item["locked_oos_metrics"]["expectancy_pnl"])
        for item in complete
    ]
    summary: dict[str, Any] = {
        "schema": "phase-48-2-locked-oos-summary-v1",
        "status": "PASS_EXECUTION_EVIDENCE",
        "asset_report_count": len(reports),
        "executed_asset_count": len(complete),
        "warmup_pending_asset_count": len(pending),
        "warmup_pending_assets": pending,
        "locked_oos_total_trade_count": total_trades,
        "positive_return_asset_count": sum(1 for value in returns if value > 0),
        "negative_return_asset_count": sum(1 for value in returns if value < 0),
        "zero_return_asset_count": sum(1 for value in returns if value == 0),
        "worst_max_drawdown_percent": str(
            max(drawdowns, default=Decimal("0"))
        ),
        "mean_profit_factor_available": (
            str(sum(profit_factors, Decimal("0")) / len(profit_factors))
            if profit_factors
            else None
        ),
        "mean_expectancy_pnl": (
            str(sum(expectancies, Decimal("0")) / len(expectancies))
            if expectancies
            else "0"
        ),
        "assets": reports,
    }
    encoded = json.dumps(
        summary,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    summary["evidence_fingerprint"] = hashlib.sha256(encoded).hexdigest()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-assets", type=int, required=True)
    parser.add_argument("--expected-pending", type=int, required=True)
    args = parser.parse_args()
    paths = list(Path(args.input_root).rglob("*.json"))
    report = aggregate(
        paths,
        expected_assets=args.expected_assets,
        expected_pending=args.expected_pending,
    )
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "asset_report_count",
                    "executed_asset_count",
                    "warmup_pending_asset_count",
                    "locked_oos_total_trade_count",
                    "evidence_fingerprint",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
