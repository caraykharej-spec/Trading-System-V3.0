from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from decimal import Decimal
from time import perf_counter

from app.data.market_data import MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.data.providers.http import ProviderError
from app.data.source_registry import SourceMappingRegistry, SourceRoute


@dataclass(frozen=True)
class SourceBenchmarkResult:
    base_asset: str
    provider: str
    provider_symbol: str
    success: bool
    latency_seconds: Decimal
    average_request_latency_seconds: Decimal
    price_deviation_percent: Decimal | None
    candle_counts: dict[str, int]
    volume_available: bool
    qualified: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["latency_seconds"] = str(self.latency_seconds)
        result["average_request_latency_seconds"] = str(
            self.average_request_latency_seconds
        )
        if self.price_deviation_percent is not None:
            result["price_deviation_percent"] = str(self.price_deviation_percent)
        return result


class SourceBenchmark:
    """Measure source latency and quality without changing the source registry."""

    def __init__(
        self,
        registry: SourceMappingRegistry,
        providers: dict[str, MarketDataProvider],
        *,
        timeframes: tuple[str, ...] = ("1d", "4h", "1h", "15m"),
        candle_limit: int = 260,
        max_workers: int = 12,
    ) -> None:
        self.registry = registry
        self.providers = providers
        self.timeframes = timeframes
        self.candle_limit = candle_limit
        self.max_workers = max_workers

    def run(
        self,
        storm_prices: dict[str, Decimal],
        *,
        assets: set[str] | None = None,
    ) -> tuple[SourceBenchmarkResult, ...]:
        selected = {item.upper() for item in assets} if assets is not None else None
        jobs = [
            (mapping.base_asset, mapping.minimum_candles,
             mapping.max_price_deviation_percent, route, storm_prices.get(mapping.base_asset))
            for mapping in self.registry.all()
            if selected is None or mapping.base_asset in selected
            for route in mapping.routes
        ]
        with ThreadPoolExecutor(
            max_workers=min(self.max_workers, max(1, len(jobs))),
            thread_name_prefix="source-benchmark",
        ) as executor:
            results = tuple(executor.map(lambda args: self._measure(*args), jobs))
        return tuple(sorted(results, key=lambda item: (item.base_asset, item.provider)))

    def _measure(
        self,
        base_asset: str,
        minimum_candles: int,
        max_deviation: Decimal,
        route: SourceRoute,
        storm_price: Decimal | None,
    ) -> SourceBenchmarkResult:
        started = perf_counter()
        counts: dict[str, int] = {}
        try:
            provider = self.providers[route.provider]
            live = provider.get_live_price(route.symbol)
            normalized = live.price * route.price_multiplier
            deviation = (
                abs(normalized - storm_price) / storm_price * Decimal("100")
                if storm_price is not None and storm_price > 0
                else None
            )
            volume_available = False
            for timeframe in self.timeframes:
                candles = provider.get_candles(
                    MarketDataRequest(route.symbol, timeframe, self.candle_limit)
                )
                counts[timeframe] = len(candles)
                volume_available = volume_available or any(c.volume > 0 for c in candles)
            enough_history = all(
                count >= minimum_candles for count in counts.values()
            )
            price_ok = deviation is None or deviation <= max_deviation
            volume_ok = not route.requires_volume or volume_available
            latency = Decimal(str(round(perf_counter() - started, 3)))
            request_count = Decimal(1 + len(self.timeframes))
            average_latency = (latency / request_count).quantize(Decimal("0.001"))
            latency_ok = average_latency <= route.max_latency_seconds
            qualified = enough_history and price_ok and volume_ok and latency_ok
            reasons = []
            if not enough_history:
                reasons.append("insufficient_history")
            if not price_ok:
                reasons.append("price_mismatch")
            if not volume_ok:
                reasons.append("volume_unavailable")
            if not latency_ok:
                reasons.append("latency_budget_exceeded")
            return SourceBenchmarkResult(
                base_asset, route.provider, route.symbol, True, latency, average_latency,
                deviation, counts, volume_available, qualified,
                "qualified" if qualified else ";".join(reasons),
            )
        except (KeyError, ProviderError) as exc:
            latency = Decimal(str(round(perf_counter() - started, 3)))
            return SourceBenchmarkResult(
                base_asset, route.provider, route.symbol, False, latency, latency,
                None, counts, False, False, type(exc).__name__,
            )
