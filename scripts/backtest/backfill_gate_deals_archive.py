from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from app.data.gateio_deals_archive import (
    GateDealsArchivePolicy,
    collect_gate_deals_archive_dataset,
)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconstruct and lock Gate OHLCV from an official monthly spot deals archive."
    )
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--archive-month", required=True)
    parser.add_argument("--start", required=True, type=_parse_utc)
    parser.add_argument("--end", required=True, type=_parse_utc)
    parser.add_argument("--dataset-version", default="1.0.0")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-backoff-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--git-revision", default="UNKNOWN")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    bundle = collect_gate_deals_archive_dataset(
        symbol=args.symbol,
        archive_month=args.archive_month,
        start=args.start,
        end=args.end,
        output_dir=args.output_dir,
        dataset_version=args.dataset_version,
        policy=GateDealsArchivePolicy(
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
            timeout_seconds=args.timeout_seconds,
        ),
        code_revision=args.git_revision,
    )

    print("GATE DEALS ARCHIVE BACKFILL COMPLETE")
    print(f"symbol={bundle.manifest['symbol']}")
    print(f"start={bundle.manifest['requested_start']}")
    print(f"end={bundle.manifest['requested_end']}")
    print(f"dataset_bundle_fingerprint={bundle.manifest['dataset_bundle_fingerprint']}")
    print(f"manifest_fingerprint={bundle.manifest['manifest_fingerprint']}")
    source = bundle.manifest.get("archive_source")
    if isinstance(source, dict):
        print(f"archive_uri={source.get('source_uri')}")
        print(f"archive_sha256={source.get('compressed_sha256')}")
        print(f"archive_bytes={source.get('compressed_bytes')}")
        print(f"in_range_trade_rows={source.get('in_range_trade_rows')}")
        print(f"base_5m_candle_count={source.get('base_5m_candle_count')}")
    for timeframe, candles in bundle.candles_by_timeframe.items():
        print(f"{timeframe}_candles={len(candles)}")
    print(f"manifest={args.output_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
