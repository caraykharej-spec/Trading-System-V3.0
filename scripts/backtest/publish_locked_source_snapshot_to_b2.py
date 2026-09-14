from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.data.locked_source_object_store import publish_locked_source_snapshot
from app.data.research_object_store import AwsCliB2Repository


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish an exact verified locked dataset snapshot to Backblaze B2."
    )
    parser.add_argument("--dataset-dir", required=True, type=Path)
    args = parser.parse_args()

    repository = AwsCliB2Repository.from_environment()
    bundle = publish_locked_source_snapshot(args.dataset_dir, repository)
    symbol = bundle.manifest["symbol"]
    fingerprint = bundle.manifest["dataset_bundle_fingerprint"]
    slug = str(symbol).replace("/", "-").replace("_", "-").lower()
    print(
        json.dumps(
            {
                "status": "LOCKED_SOURCE_PUBLISHED_AND_VERIFIED",
                "symbol": symbol,
                "dataset_bundle_fingerprint": fingerprint,
                "manifest_fingerprint": bundle.manifest["manifest_fingerprint"],
                "object_prefix": (
                    f"gold/locked-source-snapshots/v1/{slug}/{fingerprint}"
                ),
                "mode": "RESEARCH_PAPER_ONLY",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
