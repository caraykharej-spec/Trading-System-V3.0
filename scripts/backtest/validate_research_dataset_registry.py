from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HEX64 = re.compile(r"^[0-9a-f]{64}$")
TIMEFRAMES = ["15m", "1h", "4h", "1d"]


def validate(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "1.0":
        raise ValueError("unsupported registry schema")
    if raw.get("mode") != "RESEARCH_PAPER_ONLY":
        raise ValueError("registry must be research/paper only")
    datasets = raw.get("datasets")
    if not isinstance(datasets, dict) or not datasets:
        raise ValueError("registry datasets missing")

    seen: set[str] = set()
    for dataset_id, item in datasets.items():
        if not isinstance(dataset_id, str) or not isinstance(item, dict):
            raise ValueError("invalid dataset record")
        symbol = item.get("symbol")
        fingerprint = item.get("dataset_bundle_fingerprint")
        manifest_fingerprint = item.get("manifest_fingerprint")
        if not isinstance(symbol, str) or not isinstance(fingerprint, str):
            raise ValueError(f"identity missing: {dataset_id}")
        if not HEX64.fullmatch(fingerprint):
            raise ValueError(f"dataset fingerprint invalid: {dataset_id}")
        if not isinstance(manifest_fingerprint, str) or not HEX64.fullmatch(manifest_fingerprint):
            raise ValueError(f"manifest fingerprint invalid: {dataset_id}")
        if fingerprint in seen:
            raise ValueError("duplicate dataset fingerprint")
        seen.add(fingerprint)
        slug = symbol.replace("/", "-").replace("_", "-").lower()
        expected_prefix = f"gold/locked-source-snapshots/v1/{slug}/{fingerprint}"
        expected_cache = f"research-lock-{slug}-{fingerprint}"
        if item.get("object_prefix") != expected_prefix:
            raise ValueError(f"object prefix mismatch: {dataset_id}")
        if item.get("actions_cache_key") != expected_cache:
            raise ValueError(f"cache key mismatch: {dataset_id}")
        if item.get("timeframes") != TIMEFRAMES:
            raise ValueError(f"timeframe contract mismatch: {dataset_id}")
        if item.get("storage_class") != "GOLD_LOCKED_SOURCE_SNAPSHOT":
            raise ValueError(f"storage class mismatch: {dataset_id}")
        if item.get("status") not in {"ACTIVE_LOCKED", "RETIRED_LOCKED"}:
            raise ValueError(f"status invalid: {dataset_id}")
    return raw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="config/research/dataset_registry.json")
    parser.add_argument("--dataset-id")
    parser.add_argument("--github-output")
    args = parser.parse_args()
    raw = validate(Path(args.registry))
    datasets = raw["datasets"]
    assert isinstance(datasets, dict)
    if args.dataset_id:
        item = datasets.get(args.dataset_id)
        if not isinstance(item, dict) or item.get("status") != "ACTIVE_LOCKED":
            raise ValueError(f"active governed dataset not found: {args.dataset_id}")
        output = {
            "dataset_id": args.dataset_id,
            "symbol": item["symbol"],
            "dataset_fingerprint": item["dataset_bundle_fingerprint"],
            "manifest_fingerprint": item["manifest_fingerprint"],
            "object_prefix": item["object_prefix"],
            "cache_key": item["actions_cache_key"],
            "evaluation_start": item["evaluation_start"],
            "evaluation_end_exclusive": item["evaluation_end_exclusive"],
        }
        if args.github_output:
            with Path(args.github_output).open("a", encoding="utf-8") as handle:
                for key, value in output.items():
                    handle.write(f"{key}={value}\n")
        print(json.dumps(output, sort_keys=True))
    else:
        print(json.dumps({"status": "REGISTRY_VALID", "datasets": len(datasets)}, sort_keys=True))


if __name__ == "__main__":
    main()
