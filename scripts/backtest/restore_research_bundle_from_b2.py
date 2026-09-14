from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.data.research_object_restore import restore_research_bundle
from app.data.research_object_store import AwsCliB2Repository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore and verify a GOLD locked-research dataset from Backblaze B2."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--dataset-fingerprint", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    repository = AwsCliB2Repository.from_environment()
    bundle, cache_hit = restore_research_bundle(
        repository,
        symbol=args.symbol,
        dataset_fingerprint=args.dataset_fingerprint,
        destination=Path(args.output_dir),
    )
    print(
        json.dumps(
            {
                "status": "CACHE_HIT_VERIFIED" if cache_hit else "RESTORED_AND_VERIFIED",
                "symbol": bundle.manifest["symbol"],
                "dataset_fingerprint": bundle.dataset_fingerprint,
                "object_prefix": bundle.object_prefix,
                "qualification_status": bundle.manifest["qualification_status"],
                "output_dir": str(Path(args.output_dir)),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
