from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.data.providers.http import HttpClient, ProviderError, to_decimal, utc_now


@dataclass(frozen=True)
class YahooFinanceProvider(MarketDataProvider):
    name: str = "yahoo"
    base_url: str = "https://query1.finance.yahoo.com"
    client: HttpClient = HttpClient()

    def get_live_price(self, symbol: str) -> LivePrice:
        chart = self._chart(symbol, range_value="1d", interval="1m")
        result = chart.get("chart", {}).get("result") or []
        if not result:
            raise ProviderError(f"Yahoo chart not found: {symbol}")
        data = result[0]
        meta = data.get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            raise ProviderError(f"Yahoo live price unavailable: {symbol}")
        as_of = utc_now()
        return LivePrice(symbol=symbol, price=to_decimal(price), as_of=as_of, provider=self.name)

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        interval = request.timeframe or "1h"
        chart = self._chart(request.symbol, range_value=self._default_range(interval), interval=interval)
        result = chart.get("chart", {}).get("result") or []
        if not result:
            raise ProviderError(f"Yahoo candles not found: {request.symbol}")
        data = result[0]
        timestamps = data.get("timestamp") or []
        quotes = data.get("indicators", {}).get("quote") or []
        if not quotes:
            raise ProviderError(f"Yahoo quote data missing: {request.symbol}")
        quote_data = quotes[0]
        candles: list[Candle] = []
        for i, ts in enumerate(timestamps):
            values = {}
            for key in ("open", "high", "low", "close", "volume"):
                series = quote_data.get(key) or []
                values[key] = series[i] if i < len(series) else None
            if any(value is None for value in values.values()):
                continue
            candles.append(Candle(
                symbol=request.symbol,
                timeframe=interval,
                timestamp=datetime.fromtimestamp(float(ts), tz=timezone.utc),
                open=to_decimal(values["open"]),
                high=to_decimal(values["high"]),
                low=to_decimal(values["low"]),
                close=to_decimal(values["close"]),
                volume=to_decimal(values["volume"]),
            ))
        return sorted(candles, key=lambda candle: candle.timestamp)[-request.limit:]

    def _chart(self, symbol: str, *, range_value: str, interval: str):
        encoded = quote(symbol, safe="")
        url = f"{self.base_url}/v8/finance/chart/{encoded}?range={range_value}&interval={interval}"
        payload = self.client.get_json(url)
        error = payload.get("chart", {}).get("error") if isinstance(payload, dict) else None
        if error:
            raise ProviderError(str(error))
        return payload

    @staticmethod
    def _default_range(interval: str) -> str:
        return {"15m": "1mo", "1h": "3mo", "4h": "1y", "1d": "2y"}.get(interval, "3mo")
