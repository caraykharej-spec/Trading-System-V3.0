from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.data.locked_source_object_store import restore_locked_source_snapshot
from app.data.research_object_store import AwsCliB2Repository


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore and verify an exact locked dataset snapshot from Backblaze B2."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--dataset-fingerprint", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    repository = AwsCliB2Repository.from_environment()
    bundle, cache_hit = restore_locked_source_snapshot(
        repository,
        symbol=args.symbol,
        dataset_fingerprint=args.dataset_fingerprint,
        destination=args.output_dir,
    )
    print(
        json.dumps(
            {
                "status": (
                    "LOCKED_SOURCE_CACHE_HIT_VERIFIED"
                    if cache_hit
                    else "LOCKED_SOURCE_RESTORED_AND_VERIFIED"
                ),
                "symbol": bundle.manifest["symbol"],
                "dataset_bundle_fingerprint": bundle.manifest[
                    "dataset_bundle_fingerprint"
                ],
                "manifest_fingerprint": bundle.manifest["manifest_fingerprint"],
                "output_dir": str(args.output_dir),
                "mode": "RESEARCH_PAPER_ONLY",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
