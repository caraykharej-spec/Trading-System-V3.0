from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.market_data import Candle, LivePrice
from app.data.providers.http import HttpClient, ProviderError, to_decimal, utc_now


@dataclass(frozen=True)
class GateIOProvider:
    base_url: str = "https://api.gateio.ws/api/v4"
    client: HttpClient = HttpClient()

    def get_live_price(self, symbol: str) -> LivePrice:
        pair = symbol.replace("/", "_").upper()
        payload = self.client.get_json(f"{self.base_url}/spot/tickers?currency_pair={pair}")
        if not isinstance(payload, list) or not payload:
            raise ProviderError(f"Gate.io ticker not found: {symbol}")
        price = to_decimal(payload[0].get("last"))
        if price <= 0:
            raise ProviderError(f"Gate.io returned non-positive price for {symbol}")
        return LivePrice(symbol=symbol, price=price, timestamp=utc_now(), provider="gateio")

    def get_candles(self, symbol: str, interval: str, limit: int = 500) -> tuple[Candle, ...]:
        pair = symbol.replace("/", "_").upper()
        url = f"{self.base_url}/spot/candlesticks?currency_pair={pair}&interval={interval}&limit={limit}"
        payload = self.client.get_json(url)
        if not isinstance(payload, list):
            raise ProviderError(f"Gate.io candles invalid for {symbol}")
        candles: list[Candle] = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                continue
            ts = row[0]
            candles.append(Candle(
                symbol=symbol,
                interval=interval,
                timestamp=__import__("datetime").datetime.fromtimestamp(float(ts), tz=__import__("datetime").timezone.utc),
                open=to_decimal(row[5]),
                high=to_decimal(row[3]),
                low=to_decimal(row[4]),
                close=to_decimal(row[2]),
                volume=to_decimal(row[1]),
            ))
        return tuple(sorted(candles, key=lambda c: c.timestamp))
