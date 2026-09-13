from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.data.historical_store import SQLiteCandleStore
from app.data.incremental_candle_cache import IncrementalCandleService
from app.data.market_data import Candle
from app.universe.market_data_resolution import (
    AssetDataResolution,
    ResolutionSource,
    ResolvedCandleBatch,
)


class Resolver:
    def __init__(self) -> None:
        self.limits: list[int] = []

    def get_candles_with_provenance(
        self,
        resolution: AssetDataResolution,
        *,
        timeframe: str,
        limit: int,
        minimum_history: int | None = None,
    ) -> ResolvedCandleBatch:
        del minimum_history
        self.limits.append(limit)
        end = datetime(2026, 9, 13, tzinfo=timezone.utc)
        candles = tuple(
            Candle(
                resolution.canonical_symbol,
                timeframe,
                end - timedelta(hours=limit - index - 1),
                Decimal("99"),
                Decimal("101"),
                Decimal("98"),
                Decimal("100"),
                Decimal("10"),
            )
            for index in range(limit)
        )
        return ResolvedCandleBatch(
            candles,
            "gateio",
            "yahoo",
            "BTC-USD",
            True,
        )


def resolution() -> AssetDataResolution:
    return AssetDataResolution(
        "BTC",
        "BTC/USDT",
        Decimal("100"),
        "BTC/USDT",
        ResolutionSource.GATEIO,
        "BTC_USDT",
        Decimal("100"),
        Decimal("0"),
        "test",
        "gateio",
    )


def test_cold_load_persists_full_history_and_warm_load_refreshes_tail(tmp_path):
    resolver = Resolver()
    store = SQLiteCandleStore(tmp_path / "candles.db")
    service = IncrementalCandleService(resolver, store, refresh_tail=2)

    cold = service.load(resolution(), timeframe="1h", limit=260, minimum_history=220)
    warm = service.load(resolution(), timeframe="1h", limit=260, minimum_history=220)

    assert resolver.limits == [260, 2]
    assert len(cold.candles) == len(warm.candles) == 260
    assert cold.cache_candles == 0
    assert warm.cache_candles == 260
    assert warm.downloaded_candles == 2
    assert warm.actual_provider == "yahoo"
    assert warm.fallback_used
    assert len(store.load("BTC/USDT", "1h", limit=300)) == 260
