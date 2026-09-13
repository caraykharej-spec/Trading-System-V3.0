from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.backtest.baseline_runner import BaselineRunPolicy, run_live_baseline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a research-only historical baseline backtest using public Gate.io OHLCV."
    )
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--dataset-version", default="1.0.0")
    parser.add_argument(
        "--output",
        default="artifacts/backtest/baseline.json",
    )
    parser.add_argument(
        "--git-revision",
        default=os.environ.get("GITHUB_SHA", "UNKNOWN"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_live_baseline(
        symbol=args.symbol,
        policy=BaselineRunPolicy(
            candle_limit=args.limit,
            dataset_version=args.dataset_version,
        ),
        code_revision=args.git_revision,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    output.write_text(rendered, encoding="utf-8")

    result = report["result"]
    assert isinstance(result, dict)
    print("BASELINE BACKTEST COMPLETE")
    print(f"symbol={report['symbol']}")
    print(f"dataset_bundle_fingerprint={report['dataset_bundle_fingerprint']}")
    print(f"evidence_fingerprint={report['evidence_fingerprint']}")
    print(f"trade_count={result['trade_count']}")
    print(f"final_equity={result['final_equity']}")
    print(f"total_return_percent={result['total_return_percent']}")
    print(f"max_drawdown_percent={result['max_drawdown_percent']}")
    print(f"win_rate_percent={result['win_rate_percent']}")
    print(f"profit_factor={result['profit_factor']}")
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
