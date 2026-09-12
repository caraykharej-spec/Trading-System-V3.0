from __future__ import annotations

import argparse
from pathlib import Path

from app.system_qualification.scenarios import run_default_qualification


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled offline system qualification")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_default_qualification()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.to_json() + "\n", encoding="utf-8")
    print(f"Full system qualification: {report.status} ({report.passed}/{len(report.cases)})")
    if report.status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
