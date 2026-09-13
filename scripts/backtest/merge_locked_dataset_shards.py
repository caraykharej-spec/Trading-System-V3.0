from __future__ import annotations

import argparse
from pathlib import Path

from app.data.locked_dataset_merge import merge_locked_dataset_shards


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge verified contiguous locked dataset shards into one locked bundle."
    )
    parser.add_argument("--shard-dir", action="append", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--dataset-version", default="1.0.0")
    parser.add_argument("--git-revision", default="UNKNOWN")
    args = parser.parse_args()

    bundle = merge_locked_dataset_shards(
        list(args.shard_dir),
        output_dir=args.output_dir,
        dataset_version=args.dataset_version,
        code_revision=args.git_revision,
    )
    print("LOCKED DATASET SHARD ASSEMBLY COMPLETE")
    print(f"symbol={bundle.manifest['symbol']}")
    print(f"start={bundle.manifest['requested_start']}")
    print(f"end={bundle.manifest['requested_end']}")
    print(
        "dataset_bundle_fingerprint="
        f"{bundle.manifest['dataset_bundle_fingerprint']}"
    )
    print(f"manifest_fingerprint={bundle.manifest['manifest_fingerprint']}")
    print(f"source_shards_fingerprint={bundle.manifest['source_shards_fingerprint']}")
    for timeframe, candles in bundle.candles_by_timeframe.items():
        print(f"{timeframe}_candles={len(candles)}")
    print(f"manifest={args.output_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
