from datetime import datetime, timezone

from app.context.events.biquote import BiQuoteCalendarProvider
from app.context.news.rss import RSSNewsProvider


class FakeRSSProvider(RSSNewsProvider):
    def __init__(self, payload: bytes) -> None:
        super().__init__("fake", "https://example.invalid/feed")
        self.payload = payload

    def _fetch_bytes(self) -> bytes:
        return self.payload


class FakeCalendarProvider(BiQuoteCalendarProvider):
    def __init__(self, payload: object) -> None:
        super().__init__("https://example.invalid/calendar")
        self.payload = payload

    def _fetch_json(self) -> object:
        return self.payload


def test_rss_provider_parses_rss_and_timezone():
    payload = b'''<?xml version="1.0"?><rss><channel><item><title>CPI update</title><link>https://example/news/1</link><pubDate>Thu, 10 Sep 2026 12:00:00 GMT</pubDate></item></channel></rss>'''
    items = FakeRSSProvider(payload).fetch(limit=5)
    assert len(items) == 1
    assert items[0].title == "CPI update"
    assert items[0].published_at == datetime(2026, 9, 10, 12, tzinfo=timezone.utc)


def test_rss_provider_rejects_non_positive_limit():
    try:
        FakeRSSProvider(b"<rss/>").fetch(limit=0)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_biquote_calendar_provider_normalizes_event():
    payload = [{"id": "cpi-1", "name": "CPI", "date": "2026-09-10T12:00:00Z", "country": "US", "currency": "USD", "importance": "HIGH", "actual": "3.1", "forecast": "3.0", "previous": "2.9"}]
    events = FakeCalendarProvider(payload).fetch(limit=5)
    assert len(events) == 1
    assert events[0].currency == "USD"
    assert events[0].actual == 3.1
    assert events[0].forecast == 3.0
    assert events[0].surprise == 0.1


def test_biquote_calendar_skips_invalid_rows():
    events = FakeCalendarProvider([{"name": "missing time"}, "invalid"]).fetch()
    assert events == []
