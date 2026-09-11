from __future__ import annotations

from dataclasses import dataclass

from app.data.provider_router import MarketProvider, ProviderRouter


@dataclass(frozen=True)
class MarketDataSourcePolicy:
    """Explicit provider ownership for production market-data roles."""

    live_price_providers: tuple[str, ...] = ("storm",)
    ohlcv_providers: tuple[str, ...] = ("gateio", "yahoo")

    def __post_init__(self) -> None:
        if not self.live_price_providers:
            raise ValueError("at least one live-price provider is required")
        if not self.ohlcv_providers:
            raise ValueError("at least one OHLCV provider is required")
        if len(set(self.live_price_providers)) != len(self.live_price_providers):
            raise ValueError("live-price providers must be unique")
        if len(set(self.ohlcv_providers)) != len(self.ohlcv_providers):
            raise ValueError("OHLCV providers must be unique")


def build_market_data_routers(
    providers: tuple[MarketProvider, ...],
    *,
    policy: MarketDataSourcePolicy | None = None,
    max_live_age_seconds: int = 120,
) -> tuple[ProviderRouter, ProviderRouter]:
    """Build role-specific routers and fail closed on missing configured providers."""

    source_policy = policy or MarketDataSourcePolicy()
    by_name = {provider.name.lower(): provider for provider in providers}

    missing = sorted(
        set(source_policy.live_price_providers + source_policy.ohlcv_providers)
        - set(by_name)
    )
    if missing:
        raise ValueError("missing configured market-data providers: " + ", ".join(missing))

    live = tuple(by_name[name] for name in source_policy.live_price_providers)
    candles = tuple(by_name[name] for name in source_policy.ohlcv_providers)
    return (
        ProviderRouter(live, max_live_age_seconds=max_live_age_seconds),
        ProviderRouter(candles),
    )
