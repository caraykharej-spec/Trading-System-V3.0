from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from app.context.models import NewsImpact, NewsItem


class RSSNewsProvider:
    """Dependency-free RSS/Atom reader for public feeds."""

    def __init__(self, name: str, url: str, *, source: str | None = None, timeout: float = 10.0) -> None:
        self.name = name
        self.url = url
        self.source = source or name
        self.timeout = timeout

    def _fetch_bytes(self) -> bytes:
        request = Request(self.url, headers={"User-Agent": "Trading-System-V3/3.0"})
        with urlopen(request, timeout=self.timeout) as response:
            return response.read()

    @staticmethod
    def _published(value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            return parsedate_to_datetime(value).astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("RSS timestamp must be timezone-aware")
                return parsed.astimezone(timezone.utc)
            except ValueError:
                return datetime.now(timezone.utc)

    def fetch(self, *, symbol: str | None = None, limit: int = 50) -> list[NewsItem]:
        if limit < 1:
            raise ValueError("limit must be positive")
        root = ElementTree.fromstring(self._fetch_bytes())
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        result: list[NewsItem] = []
        for index, item in enumerate(items[:limit]):
            title = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or ""
            link = item.findtext("link") or ""
            if not link:
                atom_link = item.find("{http://www.w3.org/2005/Atom}link")
                link = atom_link.attrib.get("href", "") if atom_link is not None else ""
            published = item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date") or item.findtext("{http://www.w3.org/2005/Atom}published")
            if not title.strip():
                continue
            item_id = link or f"{self.name}:{index}:{title}"
            result.append(NewsItem(item_id=item_id, title=title.strip(), published_at=self._published(published), source=self.source, symbol=symbol, impact=NewsImpact.UNKNOWN))
        return result
