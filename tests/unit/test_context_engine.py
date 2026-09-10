from datetime import datetime, timedelta, timezone

from app.context.context_engine import ContextEngine
from app.context.models import EconomicEvent, EventImportance, NewsImpact, NewsItem

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def news(impact=NewsImpact.NEUTRAL, age=1, symbol="BTC/USDT"):
    return NewsItem("n1", "test", NOW - timedelta(hours=age), "test", symbol, impact)


def event(importance=EventImportance.MEDIUM, minutes=0, symbols=()):
    return EconomicEvent("e1", "CPI", NOW + timedelta(minutes=minutes), "US", importance, 101, 100, 99, symbols)


def test_critical_event_blocks():
    result = ContextEngine().assess("BTC/USDT", events=[event(EventImportance.CRITICAL)], now=NOW)
    assert result.blocking is True
    assert result.event == EventImportance.CRITICAL
    assert result.surprise == 1


def test_high_event_delays_but_does_not_block():
    result = ContextEngine().assess("BTC/USDT", events=[event(EventImportance.HIGH)], now=NOW)
    assert result.delay is True
    assert result.blocking is False


def test_critical_post_window_is_active():
    result = ContextEngine().assess("BTC/USDT", events=[event(EventImportance.CRITICAL, minutes=-10)], now=NOW)
    assert result.blocking is True


def test_event_symbol_filter():
    result = ContextEngine().assess("ETH/USDT", events=[event(EventImportance.CRITICAL, symbols=("BTC/USDT",))], now=NOW)
    assert result.event == EventImportance.NONE


def test_adverse_news_is_reported():
    result = ContextEngine().assess("BTC/USDT", news=[news(NewsImpact.ADVERSE)], now=NOW)
    assert result.news == NewsImpact.ADVERSE
    assert result.tradable is True


def test_stale_news_is_unknown():
    result = ContextEngine().assess("BTC/USDT", news=[news(age=48)], now=NOW)
    assert result.news == NewsImpact.UNKNOWN


def test_timezone_naive_now_is_rejected():
    try:
        ContextEngine().assess("BTC/USDT", now=datetime(2026, 9, 10, 12))
    except ValueError as exc:
        assert "timezone" in str(exc)
    else:
        raise AssertionError("expected ValueError")
