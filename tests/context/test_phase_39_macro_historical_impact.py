from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.context.intelligence import HistoricalImpactEvaluator, IntelligenceCategory, enrich_macro_events
from app.context.models import EconomicEvent, EventImportance
from app.data.market_data import Candle
from app.universe.instrument import AssetClass, Instrument


NOW = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


def test_macro_event_historical_impact_measures_move_without_inventing_direction() -> None:
    instrument = Instrument(
        symbol="BTCUSD",
        asset_class=AssetClass.CRYPTO,
        base_asset="BTC",
        quote_asset="USD",
    )
    intelligence = enrich_macro_events(
        (
            EconomicEvent(
                event_id="fed-rate",
                name="FOMC interest rate decision",
                event_time=NOW,
                country="US",
                importance=EventImportance.CRITICAL,
            ),
        ),
        (instrument,),
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
            high=Decimal("104"),
            low=Decimal("98"),
            close=Decimal("103"),
            volume=Decimal("20"),
        ),
    )
    report = HistoricalImpactEvaluator().evaluate_events(
        intelligence,
        {"BTCUSD": candles},
        horizon=timedelta(hours=1),
    )
    assert report.observation_count == 1
    assert report.observations[0].category is IntelligenceCategory.MACRO
    assert report.observations[0].forward_return_percent == Decimal("3")
    assert report.mean_absolute_return_percent == Decimal("3")
