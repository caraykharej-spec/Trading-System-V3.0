from __future__ import annotations

import argparse

from app.storm_costs import StormCostService


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed unless current Storm baseline cost evidence exists for every asset."
    )
    parser.add_argument("--symbol", action="append", required=True)
    args = parser.parse_args()

    service = StormCostService()
    for symbol in args.symbol:
        snapshot = service.snapshot_for(symbol)
        service.require_complete(snapshot, ("protocol_fee_ratio", "spread_ratio"))
        if snapshot.protocol_fee_ratio.value is None or snapshot.spread_ratio.value is None:
            raise RuntimeError(f"incomplete Storm cost evidence for {symbol}")
        print(
            f"symbol={symbol} market_address={snapshot.market_address} "
            f"protocol_fee_ratio={snapshot.protocol_fee_ratio.value} "
            f"spread_ratio={snapshot.spread_ratio.value} "
            f"observed_at={snapshot.observed_at.isoformat()}"
        )

    print(f"eligible_symbols={len(args.symbol)}")
    print("MULTI-ASSET STORM COST ELIGIBILITY PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
