from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.research.multi_asset_baseline import aggregate_multi_asset_baselines


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"baseline artifact must contain a JSON object: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and aggregate comparable multi-asset locked baselines."
    )
    parser.add_argument("--baseline", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    report = aggregate_multi_asset_baselines(_load(path) for path in args.baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    print("MULTI-ASSET LOCKED BASELINE AGGREGATE COMPLETE")
    print(f"asset_count={report['asset_count']}")
    print(f"symbols={','.join(report['symbols'])}")
    print(f"total_trade_count={report['total_trade_count']}")
    print(f"profitable_asset_count={report['profitable_asset_count']}")
    print(f"aggregate_fingerprint={report['aggregate_fingerprint']}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
