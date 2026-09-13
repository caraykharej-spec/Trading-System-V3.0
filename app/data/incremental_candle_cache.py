from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import perf_counter

from app.data.historical_store import CandleHistoryStore
from app.data.market_data import Candle
from app.data.providers.http import ProviderError
from app.universe.market_data_resolution import (
    AssetDataResolution,
    StormDrivenUniverseResolver,
)


@dataclass(frozen=True)
class IncrementalCandleBatch:
    candles: tuple[Candle, ...]
    configured_provider: str
    actual_provider: str
    provider_symbol: str
    fallback_used: bool
    cache_candles: int
    downloaded_candles: int
    fetch_seconds: float


class IncrementalCandleService:
    """Persist canonical candles and refresh only the mutable series tail."""

    def __init__(
        self,
        resolver: StormDrivenUniverseResolver,
        store: CandleHistoryStore,
        *,
        refresh_tail: int = 2,
    ) -> None:
        if refresh_tail < 1:
            raise ValueError("refresh_tail must be positive")
        self.resolver = resolver
        self.store = store
        self.refresh_tail = refresh_tail
        self._locks: dict[tuple[str, str], Lock] = {}
        self._locks_guard = Lock()

    def _lock_for(self, symbol: str, timeframe: str) -> Lock:
        key = (symbol.upper(), timeframe)
        with self._locks_guard:
            return self._locks.setdefault(key, Lock())

    def load(
        self,
        resolution: AssetDataResolution,
        *,
        timeframe: str,
        limit: int = 260,
        minimum_history: int = 220,
    ) -> IncrementalCandleBatch:
        if limit < < minimum_history or minimum_history < 1:
            raise ValueError("limit must be at least minimum_history")
        with self._lock_for(resolution.canonical_symbol, timeframe):
            cached = self.store.load(
                resolution.canonical_symbol, timeframe, limit=limit
            )
            missing = max(0, minimum_history - len(cached))
            fetch_limit = (
                limit
                if not cached
                else min(limit, max(self.refresh_tail, missing + self.refresh_tail))
            )
            started = perf_counter()
            fetched = self.resolver.get_candles_with_provenance(
                resolution,
                timeframe=timeframe,
                limit=fetch_limit,
                minimum_history=None,
            )
            elapsed = perf_counter() - started
            self.store.upsert(list(fetched.candles))
            merged = self.store.load(
                resolution.canonical_symbol, timeframe, limit=limit
            )
            if len(merged) < minimum_history:
                raise ProviderError(
                    f"insufficient_cached_history:{len(merged)}<{minimum_history}"
                )
            return IncrementalCandleBatch(
                candles=tuple(merged),
                configured_provider=fetched.configured_provider,
                actual_provider=fetched.actual_provider,
                provider_symbol=fetched.provider_symbol,
                fallback_used=fetched.fallback_used,
                cache_candles=len(cached),
                downloaded_candles=len(fetched.candles),
                fetch_seconds=elapsed,
            )
