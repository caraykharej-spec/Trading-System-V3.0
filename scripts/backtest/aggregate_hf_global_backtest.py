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
    returns = [Decimal(str(item["result"]["total_return_percent"])) for item in reports]
    drawdowns = [Decimal(str(item["result"]["max_drawdown_percent"])) for item in reports]
    return {
        "schema": "hf-qualified-global-backtest-summary-v1",
        "status": "PASS_COMPLETE_81_ASSET_BACKTEST",
        "mode": "RESEARCH_PAPER_ONLY",
        "asset_count": len(reports),
        "total_trade_count": sum(int(item["result"]["trade_count"]) for item in reports),
        "positive_return_asset_count": sum(value > 0 for value in returns),
        "zero_return_asset_count": sum(value == 0 for value in returns),
        "negative_return_asset_count": sum(value < 0 for value in returns),
        "median_total_return_percent": str(statistics.median(returns)),
        "worst_max_drawdown_percent": str(max(drawdowns)),
        "assets": sorted(
            (
                {
                    "base_asset": item["base_asset"],
                    "symbol": item["symbol"],
                    "evidence_fingerprint": item["evidence_fingerprint"],
                    "result": item["result"],
                }
                for item in reports
            ),
            key=lambda item: item["base_asset"],
        ),
        "limitations": (
            "Independent per-asset results are not a portfolio equity curve.",
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
    print(json.dumps({key: payload[key] for key in ("status", "asset_count", "total_trade_count")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
