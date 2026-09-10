from __future__ import annotations

from typing import Protocol

from app.context.models import NewsItem


class NewsProvider(Protocol):
    """Contract for public/no-key news sources used by the context engine."""

    name: str
    requires_credentials: bool

    def fetch(self, *, symbol: str | None = None, limit: int = 50) -> list[NewsItem]:
        ...
