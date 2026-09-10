from __future__ import annotations

from typing import Protocol

from app.context.models import NewsItem


class NewsProvider(Protocol):
    name: str

    def fetch(self, *, symbol: str | None = None, limit: int = 50) -> list[NewsItem]:
        ...
