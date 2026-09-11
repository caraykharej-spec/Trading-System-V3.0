from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.data.providers.http import HttpClient, ProviderError, to_decimal, utc_now


@dataclass(frozen=True)
class GateIOProvider(MarketDataProvider):
    """Public Gate.io market-data adapter; no API credential is required."""

    requires_credentials: ClassVar[bool] = False
    name: str = "gateio"
    base_url: str = "https://api.gateio.ws/api/v4"
    client: HttpClient = HttpClient()

    def list_live_prices(self) -> dict[str, LivePrice]:
        """Fetch the public spot ticker catalog once for universe resolution."""
        payload = self.client.get_json(f"{self.base_url}/spot/tickers")
        if not isinstance(payload, list):
            raise ProviderError("Gate.io ticker catalog returned invalid payload")
        as_of = utc_now()
        prices: dict[str, LivePrice] = {}
        for record in payload:
            if not isinstance(record, dict):
                continue
            pair = str(record.get("currency_pair") or "").upper()
            raw_price = record.get("last")
            if not pair or raw_price in (None, ""):
                continue
            price = to_decimal(raw_price)
            if price <= 0:
                continue
            prices[pair] = LivePrice(
                symbol=pair,
                price=price,
                as_of=as_of,
                provider=self.name,
            )
        return prices

    def get_live_price(self, symbol: str) -> LivePrice:
        pair = symbol.replace("/", "_").upper()
        payload = self.client.get_json(f"{self.base_url}/spot/tickers?currency_pair={pair}")
        if not isinstance(payload, list) or not payload:
            raise ProviderError(f"Gate.io ticker not found: {symbol}")
        record = payload[0]
        price = to_decimal(record.get("last"))
        if price <= 0:
            raise ProviderError(f"Gate.io returned non-positive price for {symbol}")
        as_of = utc_now()
        return LivePrice(symbol=symbol, price=price, as_of=as_of, provider=self.name)

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        timeframe = request.timeframe or "1h"
        pair = request.symbol.replace("/", "_").upper()
        limit = max(1, min(request.limit, 1000))
        url = f"{self.base_url}/spot/candlesticks?currency_pair={pair}&interval={timeframe}&limit={limit}"
        payload = self.client.get_json(url)
        if not isinstance(payload, list):
            raise ProviderError(f"Gate.io candles invalid for {request.symbol}")
        candles: list[Candle] = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                continue
            try:
                ts = float(row[0])
                candles.append(Candle(
                    symbol=request.symbol,
                    timeframe=timeframe,
                    timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                    open=to_decimal(row[5]),
                    high=to_decimal(row[3]),
                    low=to_decimal(row[4]),
                    close=to_decimal(row[2]),
                    volume=to_decimal(row[1]),
                ))
            except (TypeError, ValueError, OverflowError) as exc:
                raise ProviderError(f"Gate.io invalid candle for {request.symbol}") from exc
        return sorted(candles, key=lambda candle: candle.timestamp)
