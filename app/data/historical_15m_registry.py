from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path


DEFAULT_HISTORICAL_15M_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "market_data"
    / "historical_15m_repair_sources.json"
)


@dataclass(frozen=True)
class Historical15mRoute:
    base_asset: str
    asset_class: str
    provider: str
    symbol: str
    start: datetime
    minimum_history_days: int
    price_multiplier: Decimal = Decimal("1")
    price_divisor: Decimal = Decimal("1")
    session: str = "utc"
    listing_limited: bool = False
    proxy_for: str | None = None


class Historical15mRegistry:
    """Reviewed research-only routes used to repair short Yahoo intraday history."""

    def __init__(self, routes: tuple[Historical15mRoute, ...]) -> None:
        self._routes = {route.base_asset: route for route in routes}

    @classmethod
    def load(
        cls, path: Path = DEFAULT_HISTORICAL_15M_REGISTRY
    ) -> Historical15mRegistry:
        payload = json.loads(path.read_text(encoding="utf-8"))
        default_start = _parse_aware_datetime(payload["default_start"])
        default_minimum_days = int(payload.get("minimum_history_days", 1095))
        routes: list[Historical15mRoute] = []
        for raw_base, raw in payload["routes"].items():
            base = str(raw_base).upper()
            provider = str(raw["provider"]).lower()
            if provider not in {"alpaca_sip", "dukascopy"}:
                raise ValueError(f"unsupported historical 15m provider for {base}: {provider}")
            divisor = Decimal(str(raw.get("price_divisor", "1")))
            multiplier = Decimal(str(raw.get("price_multiplier", "1")))
            if divisor <= 0 or multiplier <= 0:
                raise ValueError(f"invalid price scaling for historical 15m route {base}")
            routes.append(
                Historical15mRoute(
                    base_asset=base,
                    asset_class=str(raw["asset_class"]),
                    provider=provider,
                    symbol=str(raw["symbol"]).upper(),
                    start=_parse_aware_datetime(raw.get("start", default_start.isoformat())),
                    minimum_history_days=int(
                        raw.get("minimum_history_days", default_minimum_days)
                    ),
                    price_multiplier=multiplier,
                    price_divisor=divisor,
                    session=str(raw.get("session", "utc")),
                    listing_limited=bool(raw.get("listing_limited", False)),
                    proxy_for=(str(raw["proxy_for"]).upper() if raw.get("proxy_for") else None),
                )
            )
        if len(routes) != len({route.base_asset for route in routes}):
            raise ValueError("historical 15m registry contains duplicate base assets")
        return cls(tuple(routes))

    def get(self, base_asset: str) -> Historical15mRoute | None:
        return self._routes.get(base_asset.upper())

    def all(self) -> tuple[Historical15mRoute, ...]:
        return tuple(sorted(self._routes.values(), key=lambda route: route.base_asset))


def _parse_aware_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("historical 15m route timestamps must include timezone")
    return parsed
