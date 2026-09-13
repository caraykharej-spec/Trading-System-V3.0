from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from app.data.historical_backfill import (
    HistoricalBackfillPolicy,
    collect_historical_dataset,
    load_locked_dataset,
)


def _timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Checkpoint/resume Gate.io historical OHLCV and lock it for "
            "reproducible research backtests."
        )
    )
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--start", required=True, type=_timestamp)
    parser.add_argument("--end", required=True, type=_timestamp)
    parser.add_argument("--dataset-version", default="1.0.0")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--chunk-points", type=int, default=900)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-backoff-seconds", type=float, default=1.0)
    parser.add_argument("--git-revision", default="UNKNOWN")
    args = parser.parse_args()

    bundle = collect_historical_dataset(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        output_dir=args.output_dir,
        dataset_version=args.dataset_version,
        policy=HistoricalBackfillPolicy(
            chunk_points=args.chunk_points,
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
        ),
        code_revision=args.git_revision,
    )
    verified = load_locked_dataset(args.output_dir)
    print("HISTORICAL BACKFILL COMPLETE")
    print(f"symbol={args.symbol}")
    print(f"start={args.start.isoformat()}")
    print(f"end={args.end.isoformat()}")
    print(
        "dataset_bundle_fingerprint="
        f"{bundle.manifest['dataset_bundle_fingerprint']}"
    )
    print(f"manifest_fingerprint={bundle.manifest['manifest_fingerprint']}")
    for timeframe, candles in verified.candles_by_timeframe.items():
        print(f"{timeframe}_candles={len(candles)}")
    print(f"manifest={args.output_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
