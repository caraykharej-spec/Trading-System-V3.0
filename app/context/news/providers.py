from __future__ import annotations

from app.context.models import NewsItem
from app.context.news.rss import RSSNewsProvider


# Public feeds: no paid API key is required for these sources.
DEFAULT_NEWS_PROVIDERS: tuple[RSSNewsProvider, ...] = (
    RSSNewsProvider("federal_reserve", "https://www.federalreserve.gov/feeds/press_all.xml", source="Federal Reserve"),
    RSSNewsProvider("sec", "https://www.sec.gov/news/pressreleases.rss", source="SEC"),
    RSSNewsProvider("ecb", "https://www.ecb.europa.eu/rss/press.html", source="ECB"),
    RSSNewsProvider("bls", "https://www.bls.gov/feed/bls_latest.rss", source="BLS"),
    RSSNewsProvider("crypto_news", "https://cryptocurrency.cv/api/rss", source="Crypto News Aggregator"),
)


def fetch_news(*, symbol: str | None = None, limit_per_provider: int = 20) -> list[NewsItem]:
    """Best-effort aggregation. A failed source does not make other sources unavailable."""
    if limit_per_provider < 1:
        raise ValueError("limit_per_provider must be positive")
    items: list[NewsItem] = []
    seen: set[str] = set()
    for provider in DEFAULT_NEWS_PROVIDERS:
        try:
            batch = provider.fetch(symbol=symbol, limit=limit_per_provider)
        except Exception:
            continue
        for item in batch:
            if item.item_id not in seen:
                seen.add(item.item_id)
                items.append(item)
    items.sort(key=lambda item: item.published_at, reverse=True)
    return items
