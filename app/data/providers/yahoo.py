from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.market_data import Candle, LivePrice
from app.data.providers.http import HttpClient, ProviderError, to_decimal, utc_now


@dataclass(frozen=True)
class YahooFinanceProvider:
    base_url: str = "https://query1.finance.yahoo.com"
    client: HttpClient = HttpClient()

    def get_live_price(self, symbol: str) -> LivePrice:
        chart = self._chart(symbol, range_value="1d", interval="1m")
        result = chart["chart"]["result"]
        if not result:
            raise ProviderError(f"Yahoo chart not found: {symbol}")
        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            raise ProviderError(f"Yahoo live price unavailable: {symbol}")
        return LivePrice(symbol=symbol, price=to_decimal(price), timestamp=utc_now(), provider="yahoo")

    def get_candles(self, symbol: str, interval: str, range_value: str = "1mo") -> tuple[Candle, ...]:
        chart = self._chart(symbol, range_value=range_value, interval=interval)
        result = chart["chart"]["result"]
        if not result:
            raise ProviderError(f"Yahoo candles not found: {symbol}")
        data = result[0]
        timestamps = data.get("timestamp") or []
        quote = (data.get("indicators", {}).get("quote") or [{}])[0]
        candles: list[Candle] = []
        for i, ts in enumerate(timestamps):
            values = {k: (quote.get(k) or [None] * len(timestamps))[i] for k in ("open", "high", "low", "close", "volume")}
            if any(v is None for v in values.values()):
                continue
            from datetime import datetime, timezone
            candles.append(Candle(
                symbol=symbol,
                interval=interval,
                timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                open=to_decimal(values["open"]),
                high=to_decimal(values["high"]),
                low=to_decimal(values["low"]),
                close=to_decimal(values["close"]),
                volume=to_decimal(values["volume"]),
            ))
        return tuple(candles)

    def _chart(self, symbol: str, *, range_value: str, interval: str):
        import urllib.parse
        encoded = urllib.parse.quote(symbol, safe="")
        url = f"{self.base_url}/v8/finance/chart/{encoded}?range={range_value}&interval={interval}"
        payload = self.client.get_json(url)
        if payload.get("chart", {}).get("error"):
            raise ProviderError(str(payload["chart"]["error"]))
        return payload
