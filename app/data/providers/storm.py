from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.data.market_data import LivePrice
from app.data.providers.http import HttpClient, ProviderError, to_decimal, utc_now


@dataclass(frozen=True)
class StormProvider:
    base_url: str = "https://api5.storm.tg/api"
    client: HttpClient = HttpClient()

    def get_live_price(self, symbol: str) -> LivePrice:
        payload = self.client.get_json(f"{self.base_url}/markets")
        record = self._find_market(payload, symbol)
        if record is None:
            raise ProviderError(f"Storm market not found: {symbol}")
        price = self._extract_price(record)
        if price <= 0:
            raise ProviderError(f"Storm returned non-positive price for {symbol}")
        return LivePrice(symbol=symbol, price=price, timestamp=utc_now(), provider="storm")

    @staticmethod
    def _find_market(payload: Any, symbol: str) -> dict[str, Any] | None:
        items = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(items, dict):
            items = items.get("markets", items.get("items", []))
        if not isinstance(items, list):
            return None
        wanted = symbol.upper().replace("/", "")
        for item in items:
            if not isinstance(item, dict):
                continue
            candidates = [item.get(k) for k in ("symbol", "name", "market", "ticker")]
            if any(str(v).upper().replace("/", "") == wanted for v in candidates if v is not None):
                return item
        return None

    @staticmethod
    def _extract_price(record: dict[str, Any]) -> Decimal:
        for key in ("price", "lastPrice", "last_price", "markPrice", "mark_price"):
            if record.get(key) is not None:
                return to_decimal(record[key])
        raise ProviderError("Storm market record has no supported price field")
