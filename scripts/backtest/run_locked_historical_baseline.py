from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.backtest.locked_baseline_runner import run_locked_historical_baseline


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a research-only baseline from a verified locked historical dataset."
    )
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--git-revision", default="UNKNOWN")
    args = parser.parse_args()

    report = run_locked_historical_baseline(
        args.dataset_dir,
        code_revision=args.git_revision,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    result = report["result"]
    if not isinstance(result, dict):
        raise RuntimeError("baseline report result payload invalid")
    print("LOCKED HISTORICAL BASELINE COMPLETE")
    print(f"symbol={report['symbol']}")
    print(f"dataset_start={report['dataset_requested_start']}")
    print(f"dataset_end={report['dataset_requested_end']}")
    print(f"dataset_bundle_fingerprint={report['dataset_bundle_fingerprint']}")
    print(f"evidence_fingerprint={report['evidence_fingerprint']}")
    print(f"trade_count={result['trade_count']}")
    print(f"rejected_signals={result['rejected_signals']}")
    print(f"final_equity={result['final_equity']}")
    print(f"total_return_percent={result['total_return_percent']}")
    print(f"max_drawdown_percent={result['max_drawdown_percent']}")
    print(f"win_rate_percent={result['win_rate_percent']}")
    print(f"profit_factor={result['profit_factor']}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
