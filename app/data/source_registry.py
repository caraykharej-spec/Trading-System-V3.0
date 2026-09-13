from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


DEFAULT_SOURCE_REGISTRY = (
    Path(__file__).resolve().parents[2] / "config" / "market_data" / "source_registry.json"
)


@dataclass(frozen=True)
class SourceRoute:
    provider: str
    symbol: str
    price_multiplier: Decimal = Decimal("1")
    requires_volume: bool = True
    max_latency_seconds: Decimal = Decimal("20")


@dataclass(frozen=True)
class SourceMapping:
    base_asset: str
    asset_class: str
    routes: tuple[SourceRoute, ...]
    minimum_candles: int = 220
    max_price_deviation_percent: Decimal = Decimal("5")


class SourceMappingRegistry:
    """Persistent, reviewable source routes selected during qualification."""

    def __init__(self, mappings: tuple[SourceMapping, ...]) -> None:
        self._mappings = {item.base_asset.upper(): item for item in mappings}

    @classmethod
    def load(cls, path: Path = DEFAULT_SOURCE_REGISTRY) -> SourceMappingRegistry:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records: list[SourceMapping] = []
        for base_asset, raw in payload["mappings"].items():
            routes = tuple(
                SourceRoute(
                    provider=str(route["provider"]),
                    symbol=str(route["symbol"]),
                    price_multiplier=Decimal(str(route.get("price_multiplier", "1"))),
                    requires_volume=bool(route.get("requires_volume", True)),
                    max_latency_seconds=Decimal(
                        str(route.get("max_latency_seconds", "20"))
                    ),
                )
                for route in raw["routes"]
            )
            if not routes:
                raise ValueError(f"source registry has no routes for {base_asset}")
            records.append(SourceMapping(
                base_asset=base_asset.upper(),
                asset_class=str(raw["asset_class"]),
                routes=routes,
                minimum_candles=int(raw.get("minimum_candles", 220)),
                max_price_deviation_percent=Decimal(
                    str(raw.get("max_price_deviation_percent", "5"))
                ),
            ))
        return cls(tuple(records))

    def get(self, base_asset: str) -> SourceMapping | None:
        return self._mappings.get(base_asset.upper())

    def all(self) -> tuple[SourceMapping, ...]:
        return tuple(sorted(self._mappings.values(), key=lambda item: item.base_asset))
