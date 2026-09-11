from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.data.providers.http import HttpClient, ProviderError, to_decimal, utc_now


STORM_PRICE_SCALE = Decimal("1000000000")


@dataclass(frozen=True)
class StormProvider(MarketDataProvider):
    """Public Storm market-data adapter; no API credential is required."""

    requires_credentials: ClassVar[bool] = False
    name: str = "storm"
    base_url: str = "https://api5.storm.tg/api"
    client: HttpClient = HttpClient()

    def list_market_records(self) -> tuple[dict[str, Any], ...]:
        """Return normalized public Storm market records from one `/markets` request."""
        payload = self.client.get_json(f"{self.base_url}/markets")
        return tuple(self._market_items(payload))

    def get_live_price(self, symbol: str) -> LivePrice:
        record = self._find_market(self.list_market_records(), symbol)
        if record is None:
            raise ProviderError(f"Storm market not found: {symbol}")
        price = self._extract_price(record)
        if price <= 0:
            raise ProviderError(f"Storm returned non-positive price for {symbol}")
        as_of = self._extract_timestamp(record) or utc_now()
        return LivePrice(symbol=symbol, price=price, as_of=as_of, provider=self.name)

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        raise ProviderError("Storm OHLCV adapter is not enabled until its candle endpoint is verified")

    @staticmethod
    def _market_items(payload: Any) -> list[dict[str, Any]]:
        items = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(items, dict):
            items = items.get("markets", items.get("items", []))
        if not isinstance(items, list):
            raise ProviderError("Storm markets response does not contain a market list")
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _mapping(record: dict[str, Any], key: str) -> dict[str, Any]:
        value = record.get(key)
        return value if isinstance(value, dict) else {}

    @classmethod
    def _find_market(
        cls,
        records: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        symbol: str,
    ) -> dict[str, Any] | None:
        wanted = cls._normalize_symbol(symbol)
        matches: list[tuple[int, dict[str, Any]]] = []
        for item in records:
            config = cls._mapping(item, "config")
            candidates = [
                item.get(key)
                for key in ("symbol", "name", "market", "ticker", "id")
            ] + [
                config.get(key)
                for key in ("ticker", "name", "id", "baseAsset", "base_asset")
            ]
            normalized = {
                cls._normalize_symbol(str(value))
                for value in candidates
                if value not in (None, "")
            }
            if wanted not in normalized:
                continue
            preferred = cls.is_reference_market(item)
            exact_ticker = cls._normalize_symbol(str(config.get("ticker") or "")) == wanted
            score = (2 if preferred else 0) + (1 if exact_ticker else 0)
            matches.append((score, item))
        if not matches:
            return None
        matches.sort(key=lambda pair: pair[0], reverse=True)
        return matches[0][1]

    @staticmethod
    def _normalize_symbol(value: str) -> str:
        return (
            value.upper()
            .replace("/", "")
            .replace("_", "")
            .replace("-", "")
            .replace(" ", "")
        )

    @classmethod
    def is_reference_market(cls, record: dict[str, Any]) -> bool:
        config = cls._mapping(record, "config")
        market_type = str(config.get("type") or record.get("type") or "").lower()
        settlement = str(
            config.get("settlementToken")
            or config.get("settlement")
            or record.get("settlement")
            or ""
        ).lower()
        return market_type == "base" and settlement == "usdt"

    @classmethod
    def _extract_price(cls, record: dict[str, Any]) -> Decimal:
        for key in ("price", "lastPrice", "last_price", "markPrice", "mark_price"):
            if record.get(key) is not None:
                return to_decimal(record[key])

        amm = cls._mapping(record, "amm")
        if amm.get("indexPrice") not in (None, ""):
            return to_decimal(amm["indexPrice"]) / STORM_PRICE_SCALE

        incentive = cls._mapping(record, "incentive")
        if incentive.get("twapIndexPrice") not in (None, ""):
            return to_decimal(incentive["twapIndexPrice"]) / STORM_PRICE_SCALE

        raise ProviderError("Storm market record has no supported price field")

    @classmethod
    def _extract_timestamp(cls, record: dict[str, Any]) -> datetime | None:
        amm = cls._mapping(record, "amm")
        config = cls._mapping(record, "config")
        candidates = [
            record.get(key) for key in ("timestamp", "updatedAt", "updated_at", "time")
        ] + [amm.get("blockTimestamp"), config.get("updatedAt")]
        for value in candidates:
            if value in (None, ""):
                continue
            parsed = cls._parse_timestamp(value)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        try:
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass

        if isinstance(value, str):
            normalized = value.strip().replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                return None
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        return None
