from __future__ import annotations

import argparse

from app.data.gateio_deals_archive import gate_deals_archive_available, gate_deals_archive_url


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed unless every required Gate monthly deals archive exists."
    )
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--month", action="append", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()

    failures: list[str] = []
    total_bytes = 0
    for month in args.month:
        available, size = gate_deals_archive_available(
            args.symbol,
            month,
            timeout_seconds=args.timeout_seconds,
        )
        print(
            f"month={month} available={available} bytes={size} "
            f"url={gate_deals_archive_url(args.symbol, month)}"
        )
        if not available:
            failures.append(month)
        if size is not None:
            total_bytes += size

    if failures:
        raise RuntimeError("missing Gate deals archive month(s): " + ", ".join(failures))
    print(f"required_months={len(args.month)}")
    print(f"combined_compressed_bytes={total_bytes}")
    print("GATE DEALS ARCHIVE AVAILABILITY PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
