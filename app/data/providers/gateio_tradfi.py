from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.data.providers.http import HttpClient, ProviderError, to_decimal, utc_now


@dataclass(frozen=True)
class GateIOTradFiProvider(MarketDataProvider):
    """Public Gate.io TradFi/CFD OHLC adapter (read-only, no credentials)."""

    requires_credentials: ClassVar[bool] = False
    name: str = "gateio_tradfi"
    base_url: str = "https://api.gateio.ws/api/v4"
    client: HttpClient = HttpClient()

    def get_live_price(self, symbol: str) -> LivePrice:
        market = symbol.upper()
        payload = self.client.get_json(
            f"{self.base_url}/tradfi/symbols/{market}/tickers"
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ProviderError(f"Gate.io TradFi ticker not found: {symbol}")
        price = to_decimal(data.get("last_price"))
        if price <= 0:
            raise ProviderError(f"Gate.io TradFi returned non-positive price for {symbol}")
        return LivePrice(symbol=symbol, price=price, as_of=utc_now(), provider=self.name)

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        timeframe = request.timeframe or "1h"
        market = request.symbol.upper()
        limit = max(1, min(request.limit, 500))
        payload = self.client.get_json(
            f"{self.base_url}/tradfi/symbols/{market}/klines"
            f"?kline_type={timeframe}&limit={limit}"
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("list") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ProviderError(f"Gate.io TradFi candles invalid for {request.symbol}")
        candles: list[Candle] = []
        for row in rows:
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
                    # Gate's public TradFi kline schema is OHLC-only.
                    volume=to_decimal(row.get("v", "0")),
                ))
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ProviderError(
                    f"Gate.io TradFi invalid candle for {request.symbol}"
                ) from exc
        return sorted(candles, key=lambda candle: candle.timestamp)
