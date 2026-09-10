from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import quote

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.data.providers.http import HttpClient, ProviderError, to_decimal, utc_now


@dataclass(frozen=True)
class YahooFinanceProvider(MarketDataProvider):
    """Public Yahoo Finance chart adapter; no API credential is required."""

    requires_credentials: ClassVar[bool] = False
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
        return LivePrice(
            symbol=symbol,
            price=to_decimal(price),
            as_of=utc_now(),
            provider=self.name,
        )

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        requested = request.timeframe or "1h"
        source_interval = "1h" if requested == "4h" else requested
        chart = self._chart(
            request.symbol,
            range_value=self._default_range(requested),
            interval=source_interval,
        )
        result = chart.get("chart", {}).get("result") or []
        if not result:
            raise ProviderError(f"Yahoo candles not found: {request.symbol}")
        data = result[0]
        candles = self._parse_candles(data, request.symbol, source_interval)
        if requested == "4h":
            candles = self._aggregate_four_hour(candles, request.symbol)
        return candles[-request.limit :]

    @staticmethod
    def _parse_candles(
        data: dict[str, Any], symbol: str, timeframe: str
    ) -> list[Candle]:
        timestamps = data.get("timestamp") or []
        quotes = data.get("indicators", {}).get("quote") or []
        if not quotes:
            raise ProviderError(f"Yahoo quote data missing: {symbol}")
        quote_data = quotes[0]
        candles: list[Candle] = []
        for index, raw_timestamp in enumerate(timestamps):
            values: dict[str, Any] = {}
            for key in ("open", "high", "low", "close", "volume"):
                series = quote_data.get(key) or []
                values[key] = series[index] if index < len(series) else None
            if any(value is None for value in values.values()):
                continue
            candles.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=datetime.fromtimestamp(
                        float(raw_timestamp), tz=timezone.utc
                    ),
                    open=to_decimal(values["open"]),
                    high=to_decimal(values["high"]),
                    low=to_decimal(values["low"]),
                    close=to_decimal(values["close"]),
                    volume=to_decimal(values["volume"]),
                )
            )
        return sorted(candles, key=lambda candle: candle.timestamp)

    @staticmethod
    def _aggregate_four_hour(
        candles: list[Candle], symbol: str
    ) -> list[Candle]:
        """Aggregate Yahoo-supported 1h bars into UTC-aligned 4h OHLCV bars."""
        buckets: dict[int, list[Candle]] = {}
        four_hours = 4 * 60 * 60
        for candle in candles:
            epoch = int(candle.timestamp.timestamp())
            bucket = epoch - (epoch % four_hours)
            buckets.setdefault(bucket, []).append(candle)

        result: list[Candle] = []
        for bucket, rows in sorted(buckets.items()):
            ordered = sorted(rows, key=lambda candle: candle.timestamp)
            result.append(
                Candle(
                    symbol=symbol,
                    timeframe="4h",
                    timestamp=datetime.fromtimestamp(bucket, tz=timezone.utc),
                    open=ordered[0].open,
                    high=max(candle.high for candle in ordered),
                    low=min(candle.low for candle in ordered),
                    close=ordered[-1].close,
                    volume=sum(
                        (candle.volume for candle in ordered), to_decimal(0)
                    ),
                )
            )
        return result

    def _chart(
        self, symbol: str, *, range_value: str, interval: str
    ) -> dict[str, Any]:
        encoded = quote(symbol, safe="")
        url = (
            f"{self.base_url}/v8/finance/chart/{encoded}"
            f"?range={range_value}&interval={interval}"
        )
        payload = self.client.get_json(url)
        if not isinstance(payload, dict):
            raise ProviderError(f"Yahoo response is not an object: {symbol}")
        error = payload.get("chart", {}).get("error")
        if error:
            raise ProviderError(str(error))
        return payload

    @staticmethod
    def _default_range(interval: str) -> str:
        return {
            "15m": "1mo",
            "1h": "3mo",
            "4h": "1y",
            "1d": "2y",
        }.get(interval, "3mo")
