from decimal import Decimal

import pytest

from app.application.opportunity_pipeline import OpportunityPipeline, RiskContext
from app.application.order_preparation import prepare_order, prepare_orders
from app.application.strategy_pipeline import StrategyPipeline
from app.core.enums import PositionSide
from app.execution.models import OrderType
from app.market.analysis import MarketSnapshot
from app.market.indicators import IndicatorSnapshot
from app.market.liquidity import LiquidityResult
from app.market.regime import RegimeResult
from app.market.structure import StructureResult
from app.market.trend import TrendResult
from app.portfolio.account import Account
from app.universe.contract_specs import ContractSpec
from app.universe.instrument import AssetClass, Instrument


def snapshot(symbol: str, timeframe: str) -> MarketSnapshot:
    indicators = IndicatorSnapshot(Decimal("100"), Decimal("99"), Decimal("95"), Decimal("55"), Decimal("2"), Decimal("100"))
    trend = TrendResult("BULLISH", "STRONG", Decimal("100"), indicators)
    return MarketSnapshot(
        symbol, timeframe, indicators, trend,
        StructureResult(Decimal("98"), Decimal("102"), False, False, False, False, Decimal("100")),
        RegimeResult("TRENDING_BULL", "NORMAL", Decimal("100")),
        LiquidityResult(Decimal("100"), Decimal("100"), Decimal("1"), Decimal("100")),
        Decimal("100"),
    )


def make_opportunity():
    pipeline = StrategyPipeline(lambda symbol: tuple(snapshot(symbol, tf) for tf in ("1D", "4H", "1H", "15M")))
    instrument = Instrument("S", AssetClass.EQUITY, "S", "USD")
    contract = ContractSpec("S", Decimal("0.01"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("20"))
    context = RiskContext(Account(Decimal("10000")), [], instrument, contract, Decimal("1"))
    result = OpportunityPipeline(pipeline, lambda symbol: context).evaluate(["S"])
    assert len(result.qualified) == 1
    return result.qualified[0]


def test_prepare_limit_order_maps_gated_signal_and_risk():
    prepared = prepare_order(make_opportunity(), created_at=None)
    assert prepared.order.order_type is OrderType.LIMIT
    assert prepared.order.side is PositionSide.LONG
    assert prepared.order.requested_price == prepared.opportunity.signal.entry
    assert prepared.order.stop_loss == prepared.opportunity.signal.stop_loss
    assert prepared.order.take_profit == prepared.opportunity.signal.target
    assert prepared.order.quantity == prepared.opportunity.risk.quantity
    assert prepared.order.leverage == prepared.opportunity.risk.leverage


def test_prepare_market_order_has_no_requested_price():
    prepared = prepare_order(make_opportunity(), order_type=OrderType.MARKET)
    assert prepared.order.order_type is OrderType.MARKET
    assert prepared.order.requested_price is None


def test_order_id_is_deterministic_for_same_opportunity():
    opportunity = make_opportunity()
    assert prepare_order(opportunity).order.order_id == prepare_order(opportunity).order.order_id


def test_prepare_orders_preserves_order_and_count():
    opportunity = make_opportunity()
    prepared = prepare_orders([opportunity, opportunity])
    assert len(prepared) == 2
    assert prepared[0].order.order_id == prepared[1].order.order_id


def test_unapproved_opportunity_cannot_be_prepared():
    opportunity = make_opportunity()
    object.__setattr__(opportunity.risk, "approved", False)
    with pytest.raises(ValueError, match="must pass risk and portfolio gates"):
        prepare_order(opportunity)
