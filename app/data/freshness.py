from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.data.market_data import LivePrice, StaleMarketDataError


def validate_live_price(price: LivePrice, max_age_seconds: int, now: datetime | None = None) -> LivePrice:
    """Reject missing/future/stale timestamps before a price is used as live."""
    if price.price <= 0:
        raise ValueError(f"Invalid live price for {price.symbol}: {price.price}")
    current = now or datetime.now(timezone.utc)
    as_of = price.as_of
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    age = current - as_of
    if age < timedelta(0):
        raise StaleMarketDataError(f"Future-dated live price for {price.symbol}")
    if age > timedelta(seconds=max_age_seconds):
        raise StaleMarketDataError(
            f"Stale live price for {price.symbol}: age={age.total_seconds():.1f}s"
        )
    return price
