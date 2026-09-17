"""Aggregate independent asset reports from the HF-qualified 81-asset backtest."""

from __future__ import annotations

import argparse
import json
import statistics
from decimal import Decimal
from pathlib import Path
from typing import Any


def aggregate(paths: list[Path]) -> dict[str, Any]:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if len(reports) != 81:
        raise ValueError(f"expected 81 asset reports, received {len(reports)}")
    bases = [str(item["base_asset"]) for item in reports]
    if len(set(bases)) != 81:
        raise ValueError("asset reports contain duplicate base assets")

    completed = [
        item
        for item in reports
        if item.get("execution_status", "COMPLETE") == "COMPLETE"
        and isinstance(item.get("result"), dict)
    ]
    warmup_pending = [
        item
        for item in reports
        if item.get("execution_status") == "WARMUP_PENDING"
        and item.get("result") is None
    ]
    if len(completed) + len(warmup_pending) != len(reports):
        raise ValueError("asset reports contain unsupported or inconsistent execution states")
    if not completed:
        raise ValueError("no completed asset backtests available for aggregation")

    returns = [Decimal(str(item["result"]["total_return_percent"])) for item in completed]
    drawdowns = [Decimal(str(item["result"]["max_drawdown_percent"])) for item in completed]
    status = (
        "PASS_QUALIFIED_UNIVERSE_WITH_WARMUP_PENDING"
        if warmup_pending
        else "PASS_COMPLETE_81_ASSET_BACKTEST"
    )

    asset_rows: list[dict[str, Any]] = []
    for item in reports:
        row: dict[str, Any] = {
            "base_asset": item["base_asset"],
            "symbol": item["symbol"],
            "execution_status": item.get("execution_status", "COMPLETE"),
            "evidence_fingerprint": item["evidence_fingerprint"],
        }
        if isinstance(item.get("result"), dict):
            row["result"] = item["result"]
        else:
            row["qualification_status"] = item.get("qualification_status")
            row["strategy_warmup_status"] = item.get("strategy_warmup_status")
            row["warmup_deficiencies"] = item.get("warmup_deficiencies", [])
        asset_rows.append(row)

    return {
        "schema": "hf-qualified-global-backtest-summary-v2",
        "status": status,
        "mode": "RESEARCH_PAPER_ONLY",
        "qualified_universe_asset_count": len(reports),
        "backtested_asset_count": len(completed),
        "warmup_pending_asset_count": len(warmup_pending),
        "warmup_pending_assets": sorted(str(item["base_asset"]) for item in warmup_pending),
        "total_trade_count": sum(int(item["result"]["trade_count"]) for item in completed),
        "positive_return_asset_count": sum(value > 0 for value in returns),
        "zero_return_asset_count": sum(value == 0 for value in returns),
        "negative_return_asset_count": sum(value < 0 for value in returns),
        "median_total_return_percent": str(statistics.median(returns)),
        "worst_max_drawdown_percent": str(max(drawdowns)),
        "assets": sorted(asset_rows, key=lambda item: item["base_asset"]),
        "limitations": (
            "Independent per-asset results are not a portfolio equity curve.",
            "Warm-up-pending listing-limited assets are excluded from performance metrics until actual minimum candles exist; no synthetic zero-return result is imputed.",
            "This is research evidence and does not authorize live trading.",
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    paths = sorted(Path(args.input_root).rglob("*.json"))
    payload = aggregate(paths)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "status",
                    "qualified_universe_asset_count",
                    "backtested_asset_count",
                    "warmup_pending_asset_count",
                    "total_trade_count",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
