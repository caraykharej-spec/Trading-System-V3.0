from app.application.runner import build_demo_runner


def main() -> None:
    runner = build_demo_runner()
    result = runner.run_cycle()

    print(f"Cycle: {result.cycle_id}")
    print(f"Status: {result.status.value}")
    print(f"Monitored positions: {result.monitored_positions}")
    print(f"Stopped positions: {result.stopped_positions}")
    for note in result.notes:
        print(note)


if __name__ == "__main__":
    main()
