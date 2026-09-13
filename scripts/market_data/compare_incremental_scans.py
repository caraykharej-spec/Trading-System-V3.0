from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def downloaded(payload: dict[str, Any]) -> int:
    return sum(
        int(item.get("downloaded_candles", 0))
        for market in payload.get("all_evaluated_markets", [])
        for item in market.get("candle_provenance", [])
    )


def reduction(cold: float, warm: float) -> float:
    return 100.0 if cold == 0 and warm == 0 else (
        0.0 if cold == 0 else ((cold - warm) / cold) * 100.0
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cold", type=Path)
    parser.add_argument("warm", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cold = load(args.cold)
    warm = load(args.warm)
    cold_downloads = downloaded(cold)
    warm_downloads = downloaded(warm)
    download_reduction = reduction(float(cold_downloads), float(warm_downloads))
    signal_reduction = reduction(
        float(cold["signal_scan_seconds"]), float(warm["signal_scan_seconds"])
    )
    total_reduction = reduction(
        float(cold["total_seconds"]), float(warm["total_seconds"])
    )
    coverage_preserved = warm["coverage_percent"] == cold["coverage_percent"]
    evidence = {
        "cold": {
            "downloaded_candles": cold_downloads,
            "coverage_percent": cold["coverage_percent"],
            "resolution_seconds": cold["resolution_seconds"],
            "signal_scan_seconds": cold["signal_scan_seconds"],
            "total_seconds": cold["total_seconds"],
        },
        "warm": {
            "downloaded_candles": warm_downloads,
            "coverage_percent": warm["coverage_percent"],
            "resolution_seconds": warm["resolution_seconds"],
            "signal_scan_seconds": warm["signal_scan_seconds"],
            "total_seconds": warm["total_seconds"],
        },
        "improvement": {
            "download_reduction_percent": round(download_reduction, 2),
            "signal_scan_reduction_percent": round(signal_reduction, 2),
            "total_cycle_reduction_percent": round(total_reduction, 2),
            "coverage_preserved": coverage_preserved,
        },
        "targets": {
            "download_reduction_at_least_90_percent": download_reduction >= 90.0,
            "signal_scan_reduction_at_least_60_percent": signal_reduction >= 60.0,
            "coverage_preserved": coverage_preserved,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence["improvement"], sort_keys=True))
    if not coverage_preserved or download_reduction < 90.0:
        raise SystemExit("incremental scan benchmark failed correctness/data target")


if __name__ == "__main__":
    main()
