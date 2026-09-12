from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.data.providers.http import HttpClient, ProviderError, to_decimal, utc_now


@dataclass(frozen=True)
class GateIOFuturesProvider(MarketDataProvider):
    """Public Gate.io USDT perpetual market data (read-only, no credentials)."""

    requires_credentials: ClassVar[bool] = False
    name: str = "gateio_futures"
    base_url: str = "https://api.gateio.ws/api/v4"
    client: HttpClient = HttpClient()

    def get_live_price(self, symbol: str) -> LivePrice:
        contract = symbol.replace("/", "_").upper()
        payload = self.client.get_json(
            f"{self.base_url}/futures/usdt/tickers?contract={contract}"
        )
        if not isinstance(payload, list) or not payload:
            raise ProviderError(f"Gate.io futures ticker not found: {symbol}")
        price = to_decimal(payload[0].get("last"))
        if price <= 0:
            raise ProviderError(f"Gate.io futures returned non-positive price for {symbol}")
        return LivePrice(symbol=symbol, price=price, as_of=utc_now(), provider=self.name)

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        timeframe = request.timeframe or "1h"
        contract = request.symbol.replace("/", "_").upper()
        limit = max(1, min(request.limit, 2000))
        payload = self.client.get_json(
            f"{self.base_url}/futures/usdt/candlesticks?contract={contract}"
            f"&interval={timeframe}&limit={limit}"
        )
        if not isinstance(payload, list):
            raise ProviderError(f"Gate.io futures candles invalid for {request.symbol}")
        candles: list[Candle] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            try:
                candles.append(Candle(
                    symbol=request.symbol,
                    timeframe=timeframe,
                    timestamp=datetime.fromtimestamp(float(row["t"]), tz=timezone.utc),
                    open=to_decimal(row["o"]),
                    high=to_decimal(row["h"]),
                    low=to_decimal(row["l"]),
                    close=to_decimal(row["c"]),
                    volume=to_decimal(row.get("sum", row.get("v", "0"))),
                ))
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ProviderError(
                    f"Gate.io futures invalid candle for {request.symbol}"
                ) from exc
        return sorted(candles, key=lambda candle: candle.timestamp)
