from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.data.providers.http import HttpClient, ProviderError, to_decimal, utc_now
from app.data.quality import timeframe_seconds


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
        payload = self.client.get_json(
            f"{self.base_url}/spot/tickers?currency_pair={pair}"
        )
        if not isinstance(payload, list) or not payload:
            raise ProviderError(f"Gate.io ticker not found: {symbol}")
        record = payload[0]
        if not isinstance(record, dict):
            raise ProviderError(f"Gate.io ticker invalid for {symbol}")
        price = to_decimal(record.get("last"))
        if price <= 0:
            raise ProviderError(f"Gate.io returned non-positive price for {symbol}")
        as_of = utc_now()
        return LivePrice(
            symbol=symbol,
            price=price,
            as_of=as_of,
            provider=self.name,
        )

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        timeframe = request.timeframe or "1h"
        pair = request.symbol.replace("/", "_").upper()
        limit = max(1, min(request.limit, 1000))
        url = (
            f"{self.base_url}/spot/candlesticks"
            f"?currency_pair={pair}&interval={timeframe}&limit={limit}"
        )
        payload = self.client.get_json(url)
        return self._parse_candles(payload, request.symbol, timeframe)

    def get_candles_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Fetch one bounded historical range using Gate.io ``from``/``to``.

        ``end`` is passed directly to Gate.io's ``to`` parameter. Callers should
        keep the theoretical point count at or below 1000 and may overlap
        adjacent windows by one timestamp to tolerate endpoint-inclusivity
        differences. ``limit`` is deliberately omitted because Gate.io rejects
        it when ``from`` or ``to`` is present.
        """

        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("historical range timestamps must be timezone-aware")
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)
        if start_utc > end_utc:
            raise ValueError("historical range start must not be after end")

        step = timeframe_seconds(timeframe)
        theoretical_points = int(
            (end_utc - start_utc).total_seconds() // step
        ) + 1
        if theoretical_points > 1000:
            raise ValueError(
                "Gate.io historical range exceeds the 1000-point request limit"
            )

        pair = symbol.replace("/", "_").upper()
        from_ts = int(start_utc.timestamp())
        to_ts = int(end_utc.timestamp())
        url = (
            f"{self.base_url}/spot/candlesticks"
            f"?currency_pair={pair}&interval={timeframe}"
            f"&from={from_ts}&to={to_ts}"
        )
        payload = self.client.get_json(url)
        return self._parse_candles(payload, symbol, timeframe)

    @staticmethod
    def _parse_candles(
        payload: Any,
        symbol: str,
        timeframe: str,
    ) -> list[Candle]:
        if not isinstance(payload, list):
            raise ProviderError(f"Gate.io candles invalid for {symbol}")
        candles: list[Candle] = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                continue
            try:
                ts = float(row[0])
                candles.append(
                    Candle(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                        open=to_decimal(row[5]),
                        high=to_decimal(row[3]),
                        low=to_decimal(row[4]),
                        close=to_decimal(row[2]),
                        volume=to_decimal(row[1]),
                    )
                )
            except (TypeError, ValueError, OverflowError) as exc:
                raise ProviderError(f"Gate.io invalid candle for {symbol}") from exc
        return sorted(candles, key=lambda candle: candle.timestamp)
