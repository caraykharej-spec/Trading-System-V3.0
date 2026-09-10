from __future__ import annotations

import argparse
from pathlib import Path

from app.application.composition import build_paper_application


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trading System V3 paper/research application"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("status", "cycle"),
        default="status",
        help="status is passive; cycle explicitly runs one PAPER runtime cycle",
    )
    parser.add_argument(
        "--db",
        default="data/trading_system_v3.db",
        help="SQLite database path",
    )
    parser.add_argument(
        "--universe",
        default="config/universe.json",
        help="universe configuration path",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    application = build_paper_application(
        db_path=Path(args.db),
        universe_path=Path(args.universe),
    )
    try:
        open_positions = application.position_repository.list_open()
        readiness = application.health.readiness()
        print(f"Mode: {application.mode.value}")
        print(f"Readiness: {readiness.state.value}")
        print(f"Account equity: {application.account.equity}")
        print(f"Open positions: {len(open_positions)}")
        print(
            "Aggregate open risk: "
            f"{application.account.aggregate_open_risk(open_positions)}"
        )

        if args.command == "cycle":
            result = application.runtime.run()
            print(f"Cycle: {result.cycle_id}")
            print(f"Status: {result.status.value}")
            print(f"Monitored positions: {result.monitored_positions}")
            print(f"Stopped positions: {result.stopped_positions}")
            for note in result.notes:
                print(note)
    finally:
        application.close()


if __name__ == "__main__":
    main()
