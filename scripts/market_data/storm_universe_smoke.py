from __future__ import annotations

from app.data.providers.storm import StormProvider
from app.universe.storm_discovery import StormReferenceUniverseProvider


def main() -> None:
    provider = StormProvider()
    records = provider.list_market_records()
    resolver = StormReferenceUniverseProvider(provider=provider)
    assets = resolver.discover()
    if not assets:
        print(f"Storm diagnostic: records={len(records)}")
        for index, record in enumerate(records[:3]):
            print(f"record[{index}] keys={sorted(record.keys())}")
            for key in (
                "symbol",
                "name",
                "market",
                "ticker",
                "id",
                "type",
                "marketType",
                "market_type",
                "settlement",
                "settlementAsset",
                "settlement_asset",
                "base",
                "baseAsset",
                "base_asset",
                "asset",
                "underlying",
                "underlyingAsset",
            ):
                if key in record:
                    print(f"record[{index}].{key}={record.get(key)!r}")
        raise RuntimeError(
            "Storm public universe smoke found no type=base settlement=usdt markets"
        )

    invalid = [
        asset
        for asset in assets
        if asset.market_type.lower() != "base"
        or asset.settlement.lower() != "usdt"
        or asset.reference_price <= 0
    ]
    if invalid:
        raise RuntimeError("Storm reference universe contains invalid filtered assets")

    print("Storm public universe smoke: PASS")
    print(f"reference_storm={len(assets)} type=base settlement=usdt")


if __name__ == "__main__":
    main()
