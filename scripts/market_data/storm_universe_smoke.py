from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.data.providers.storm import StormProvider
from app.universe.storm_discovery import StormReferenceUniverseProvider


INTERESTING = (
    "type",
    "settle",
    "base",
    "quote",
    "symbol",
    "ticker",
    "name",
    "oracle",
    "price",
    "asset",
    "market",
)


def _diagnose_mapping(value: Mapping[str, Any], prefix: str, depth: int = 0) -> None:
    if depth > 3:
        return
    print(f"{prefix} keys={sorted(str(key) for key in value.keys())}")
    for raw_key, child in value.items():
        key = str(raw_key)
        path = f"{prefix}.{key}"
        if isinstance(child, Mapping):
            _diagnose_mapping(child, path, depth + 1)
        elif any(token in key.lower() for token in INTERESTING):
            rendered = repr(child)
            if len(rendered) > 500:
                rendered = rendered[:497] + "..."
            print(f"{path}={rendered}")


def main() -> None:
    provider = StormProvider()
    records = provider.list_market_records()
    resolver = StormReferenceUniverseProvider(provider=provider)
    assets = resolver.discover()
    if not assets:
        print(f"Storm diagnostic: records={len(records)}")
        for index, record in enumerate(records[:3]):
            _diagnose_mapping(record, f"record[{index}]")
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
