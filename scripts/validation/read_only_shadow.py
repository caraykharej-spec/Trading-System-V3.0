from __future__ import annotations

import argparse
from pathlib import Path

from app.shadow_validation.venue import build_shadow_validator


def main() -> int:
    parser = argparse.ArgumentParser(description="Public GET-only venue/shadow validation")
    parser.add_argument("--universe", default="config/universe.json")
    parser.add_argument("--symbols", nargs="+", default=["BTC/USDT"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_shadow_validator(args.universe).run(tuple(args.symbols))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.to_json() + "\n", encoding="utf-8")
    print(f"Read-only venue + shadow integration: {report.status}")
    return {"PASS": 0, "HOLD": 2, "FAIL": 1}[report.status]


if __name__ == "__main__":
    raise SystemExit(main())
