#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.data.research_object_store import (
    AwsCliB2Repository,
    build_research_bundle,
    publish_research_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify an existing locked historical dataset, convert it to Parquet+ZSTD, "
            "and publish it immutably to the Backblaze B2 research data store."
        )
    )
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--git-revision", required=True)
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="Build and verify the local research bundle without publishing to B2.",
    )
    args = parser.parse_args()

    bundle = build_research_bundle(
        args.dataset_dir,
        args.bundle_dir,
        git_revision=args.git_revision,
    )

    result = {
        "status": "BUILT",
        "qualification_status": "RESEARCH_PAPER_ONLY",
        "dataset_fingerprint": bundle.dataset_fingerprint,
        "object_prefix": bundle.object_prefix,
        "manifest": str(Path(args.bundle_dir) / "manifest.json"),
    }

    if not args.build_only:
        required = ("B2_S3_ENDPOINT", "B2_BUCKET_NAME", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise SystemExit("missing required environment variables: " + ", ".join(missing))
        published = publish_research_bundle(bundle.root, AwsCliB2Repository.from_environment())
        result["status"] = "PUBLISHED_AND_VERIFIED"
        result["dataset_fingerprint"] = published.dataset_fingerprint
        result["object_prefix"] = published.object_prefix

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
