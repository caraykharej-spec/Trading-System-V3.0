from __future__ import annotations

from app.data.providers.storm import StormProvider
from app.universe.storm_discovery import StormReferenceUniverseProvider


def main() -> None:
    provider = StormProvider()
    resolver = StormReferenceUniverseProvider(provider=provider)
    assets = resolver.discover()
    if not assets:
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
