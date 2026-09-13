from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.data.providers.http import ProviderError, utc_now
from app.data.providers.storm import StormProvider


@dataclass(frozen=True)
class StormReferenceAsset:
    """One Storm market admitted to the reference data universe."""

    base_asset: str
    canonical_symbol: str
    provider_symbol: str
    market_type: str
    settlement: str
    reference_price: Decimal
    as_of: datetime


@dataclass(frozen=True)
class StormReferenceUniverseProvider:
    """Build the reference universe from Storm public markets only."""

    provider: StormProvider = StormProvider()
    required_type: str = "base"
    required_settlement: str = "usdt"
    tradable_only: bool = True

    def discover(self) -> tuple[StormReferenceAsset, ...]:
        assets: list[StormReferenceAsset] = []
        seen: set[str] = set()
        for record in self.provider.list_market_records():
            market_type = self._string(
                record, "type", "marketType", "market_type"
            ).lower()
            settlement = self._string(
                record,
                "settlementToken",
                "settlement",
                "settlementAsset",
                "settlement_asset",
            ).lower()
            if market_type != self.required_type.lower():
                continue
            if settlement != self.required_settlement.lower():
                continue
            if self.tradable_only and not self._is_tradable(record):
                continue

            base = self._extract_base_asset(record, settlement)
            if not base or base in seen:
                continue
            price = self.provider._extract_price(record)
            if price <= 0:
                continue
            provider_symbol = self._extract_provider_symbol(record, base, settlement)
            assets.append(
                StormReferenceAsset(
                    base_asset=base,
                    canonical_symbol=f"{base}/{settlement.upper()}",
                    provider_symbol=provider_symbol,
                    market_type=market_type,
                    settlement=settlement,
                    reference_price=price,
                    as_of=self.provider._extract_timestamp(record) or utc_now(),
                )
            )
            seen.add(base)

        return tuple(sorted(assets, key=lambda item: item.base_asset))

    @classmethod
    def _is_tradable(cls, record: dict[str, Any]) -> bool:
        settings = cls._mapping(record, "settings")
        config = cls._config(record)
        status = str(settings.get("status") or "active").lower()
        return (
            status == "active"
            and not bool(settings.get("isPaused", False))
            and not bool(settings.get("isCloseOnly", False))
            and not bool(config.get("isHidden", False))
        )

    @staticmethod
    def _mapping(record: dict[str, Any], key: str) -> dict[str, Any]:
        value = record.get(key)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _config(record: dict[str, Any]) -> dict[str, Any]:
        value = record.get("config")
        return value if isinstance(value, dict) else {}

    @classmethod
    def _string(cls, record: dict[str, Any], *keys: str) -> str:
        config = cls._config(record)
        for source in (record, config):
            for key in keys:
                value = source.get(key)
                if value not in (None, ""):
                    return str(value).strip()
        return ""

    @classmethod
    def _extract_base_asset(cls, record: dict[str, Any], settlement: str) -> str:
        explicit = cls._string(
            record,
            "base",
            "baseAsset",
            "base_asset",
            "asset",
            "underlying",
            "underlyingAsset",
        )
        if explicit:
            return explicit.upper()

        raw = cls._string(record, "symbol", "ticker", "market", "name", "id").upper()
        if not raw:
            return ""
        settlement_upper = settlement.upper()
        normalized = raw.replace("-", "/").replace("_", "/")
        parts = [part for part in normalized.split("/") if part]
        if len(parts) >= 2 and parts[-1] == settlement_upper:
            return parts[0]
        compact = "".join(character for character in raw if character.isalnum())
        if compact.endswith(settlement_upper) and len(compact) > len(settlement_upper):
            return compact[: -len(settlement_upper)]
        return ""

    @classmethod
    def _extract_provider_symbol(
        cls, record: dict[str, Any], base: str, settlement: str
    ) -> str:
        raw = cls._string(record, "ticker", "symbol", "market", "name", "id")
        if raw:
            return raw
        if not base:
            raise ProviderError("Storm reference market is missing a usable symbol")
        return f"{base}/{settlement.upper()}"
