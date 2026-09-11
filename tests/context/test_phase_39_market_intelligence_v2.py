from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.context.intelligence import (
    EntityResolver,
    HistoricalImpactEvaluator,
    IntelligenceCategory,
    MarketIntelligenceEngine,
    RawNewsRecord,
    deduplicate_news,
    normalize_record,
    records_from_news_items,
)
from app.context.models import EconomicEvent, EventImportance, NewsImpact, NewsItem
from app.data.market_data import Candle
from app.universe.instrument import AssetClass, Instrument


NOW = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


def _instrument(symbol: str, base: str, quote: str, asset_class: AssetClass) -> Instrument:
    return Instrument(symbol=symbol, asset_class=asset_class, base_asset=base, quote_asset=quote)


def test_normalization_and_near_duplicate_collapse() -> None:
    first = RawNewsRecord(
        raw_id="a",
        title="  SEC approved   Bitcoin ETF launch ",
        published_at=NOW - timedelta(minutes=5),
        source="Source A",
        url="https://example.com/story?utm_source=rss&id=7",
    )
    second = RawNewsRecord(
        raw_id="b",
        title="SEC approved Bitcoin ETF launch!",
        published_at=NOW - timedelta(minutes=3),
        source="Source B",
        url="https://example.com/story?id=7&utm_medium=feed",
    )
    unique = deduplicate_news([normalize_record(first), normalize_record(second)])
    assert len(unique) == 1
    assert unique[0].raw_ids == ("a", "b")
    assert unique[0].sources == ("Source A", "Source B")
    assert unique[0].url == "https://example.com/story?id=7"


def test_intelligence_pipeline_resolves_assets_classifies_and_preserves_context_block() -> None:
    btc = _instrument("BTCUSD", "BTC", "USD", AssetClass.CRYPTO)
    eurusd = _instrument("EURUSD", "EUR", "USD", AssetClass.FOREX)
    engine = MarketIntelligenceEngine(
        entity_resolver=EntityResolver({"BTCUSD": ("bitcoin", "btc")})
    )
    raw = (
        RawNewsRecord(
            raw_id="story-1",
            title="SEC approved Bitcoin ETF launch",
            published_at=NOW - timedelta(minutes=5),
            source="Example",
            body="Bitcoin adoption expands after approval.",
        ),
    )
    events = (
        EconomicEvent(
            event_id="cpi-us",
            name="US CPI inflation release",
            event_time=NOW,
            country="US",
            importance=EventImportance.CRITICAL,
        ),
    )
    snapshot = engine.process(raw, events, (btc, eurusd))
    assert len(snapshot.intelligence) == 1
    item = snapshot.intelligence[0]
    assert item.symbols == ("BTCUSD",)
    assert item.category is IntelligenceCategory.REGULATORY
    assert item.impact is NewsImpact.SUPPORTIVE
    assert item.confidence > Decimal("0.5")

    macro = snapshot.event_intelligence[0]
    assert macro.category is IntelligenceCategory.MACRO
    assert macro.event.currency == "USD"
    assert macro.event.symbols == ("BTCUSD", "EURUSD")

    assessment = engine.assess("BTCUSD", snapshot, now=NOW)
    assert assessment.context.blocking is True
    assert assessment.context.news is NewsImpact.SUPPORTIVE
    assert assessment.relevant_items == 1
    assert assessment.intelligence_confidence == item.confidence


def test_historical_impact_evaluator_scores_directional_outcome() -> None:
    btc = _instrument("BTCUSD", "BTC", "USD", AssetClass.CRYPTO)
    engine = MarketIntelligenceEngine(
        entity_resolver=EntityResolver({"BTCUSD": ("bitcoin",)})
    )
    snapshot = engine.process(
        (
            RawNewsRecord(
                raw_id="story-2",
                title="Bitcoin approved for major adoption launch",
                published_at=NOW - timedelta(minutes=5),
                source="Example",
            ),
        ),
        (),
        (btc,),
    )
    candles = (
        Candle(
            symbol="BTCUSD",
            timeframe="1h",
            timestamp=NOW,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("10"),
        ),
        Candle(
            symbol="BTCUSD",
            timeframe="1h",
            timestamp=NOW + timedelta(hours=1),
            open=Decimal("100"),
            high=Decimal("106"),
            low=Decimal("100"),
            close=Decimal("105"),
            volume=Decimal("20"),
        ),
    )
    report = HistoricalImpactEvaluator().evaluate(
        snapshot.intelligence,
        {"BTCUSD": candles},
        horizon=timedelta(hours=1),
    )
    assert report.observation_count == 1
    assert report.directional_hit_rate_percent == Decimal("100")
    assert report.mean_absolute_return_percent == Decimal("5")


def test_existing_news_provider_contract_can_bridge_into_v2() -> None:
    item = NewsItem(
        item_id="legacy-1",
        title="Bitcoin protocol upgrade launch",
        published_at=NOW,
        source="Legacy RSS",
        symbol="BTCUSD",
    )
    records = records_from_news_items([item])
    assert len(records) == 1
    assert records[0].raw_id == "legacy-1"
    assert records[0].symbol_hints == ("BTCUSD",)


def test_unrelated_news_remains_global_unknown_instead_of_inventing_asset_relevance() -> None:
    btc = _instrument("BTCUSD", "BTC", "USD", AssetClass.CRYPTO)
    snapshot = MarketIntelligenceEngine().process(
        (
            RawNewsRecord(
                raw_id="weather",
                title="Local weather update",
                published_at=NOW,
                source="Example",
            ),
        ),
        (),
        (btc,),
    )
    assert snapshot.intelligence[0].symbols == ()
    assert snapshot.intelligence[0].impact is NewsImpact.UNKNOWN
    assert snapshot.news_items[0].symbol is None
