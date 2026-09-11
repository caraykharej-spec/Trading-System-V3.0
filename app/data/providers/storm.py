from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.data.providers.http import HttpClient, ProviderError, to_decimal, utc_now


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
    def _find_market(
        records: tuple[dict[str, Any], ...] | list[dict[str, Any]], symbol: str
    ) -> dict[str, Any] | None:
        wanted = symbol.upper().replace("/", "").replace("_", "").replace("-", "")
        for item in records:
            candidates = [item.get(k) for k in ("symbol", "name", "market", "ticker", "id")]
            if any(
                str(value)
                .upper()
                .replace("/", "")
                .replace("_", "")
                .replace("-", "")
                == wanted
                for value in candidates
                if value is not None
            ):
                return item
        return None

    @staticmethod
    def _extract_price(record: dict[str, Any]) -> Decimal:
        for key in ("price", "lastPrice", "last_price", "markPrice", "mark_price"):
            if record.get(key) is not None:
                return to_decimal(record[key])
        raise ProviderError("Storm market record has no supported price field")

    @staticmethod
    def _extract_timestamp(record: dict[str, Any]) -> datetime | None:
        for key in ("timestamp", "updatedAt", "updated_at", "time"):
            value = record.get(key)
            if value is None:
                continue
            try:
                numeric = float(value)
                if numeric > 10_000_000_000:
                    numeric /= 1000
                return datetime.fromtimestamp(numeric, tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
        return None
