from decimal import Decimal
from threading import Barrier

from app.application.opportunity_pipeline import OpportunityPipeline, RiskContext
from app.application.strategy_pipeline import StrategyPipeline
from app.data.providers.http import ProviderError
from app.context.models import ContextAssessment, EventImportance, NewsImpact
from app.core.enums import PositionSide, PositionStatus
from app.core.models import Position
from app.market.analysis import MarketSnapshot
from app.market.indicators import IndicatorSnapshot
from app.market.liquidity import LiquidityResult
from app.market.regime import RegimeResult
from app.market.structure import StructureResult
from app.market.trend import TrendResult
from app.portfolio.account import Account
from app.portfolio.portfolio_engine import PortfolioPolicy
from app.universe.contract_specs import ContractSpec
from app.universe.instrument import AssetClass, Instrument


def snapshot(symbol: str, timeframe: str) -> MarketSnapshot:
    indicators = IndicatorSnapshot(Decimal("100"), Decimal("99"), Decimal("95"), Decimal("55"), Decimal("2"), Decimal("100"))
    trend = TrendResult("BULLISH", "STRONG", Decimal("100"), indicators)
    structure = StructureResult("BREAKOUT_UP", Decimal("98"), Decimal("102"), Decimal("100"))
    return MarketSnapshot(symbol, timeframe, indicators, trend, structure, RegimeResult("TRENDING_BULL", "NORMAL", Decimal("100")), LiquidityResult(Decimal("100"), Decimal("100"), Decimal("1"), Decimal("100")), Decimal("100"))


def snapshots(symbol: str):
    return tuple(snapshot(symbol, tf) for tf in ("1D", "4H", "1H", "15M"))


def context(*, leverage: str = "1", positions=None, correlation: str = "0", provider=None) -> RiskContext:
    instrument = Instrument("S", AssetClass.EQUITY, "S", "USD")
    contract = ContractSpec("S", Decimal("0.01"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("20"))
    return RiskContext(Account(Decimal("10000")), list(positions or []), instrument, contract, Decimal(leverage), provider, Decimal(correlation))


def test_storm_hard_limit_rejects_before_portfolio():
    result = OpportunityPipeline(StrategyPipeline(lambda symbol: snapshots(symbol)), lambda symbol: context(leverage="7", provider="STORM")).evaluate(["S"])
    assert result.strategy_qualified == 1
    assert result.risk_rejected == 1
    assert result.portfolio_rejected == 0
    assert result.qualified == ()


def test_portfolio_gate_can_be_stricter_than_risk_gate():
    result = OpportunityPipeline(StrategyPipeline(lambda symbol: snapshots(symbol)), lambda symbol: context(), portfolio_policy=PortfolioPolicy(max_aggregate_risk_percent=Decimal("0.5"))).evaluate(["S"])
    assert result.strategy_qualified == 1
    assert result.risk_rejected == 0
    assert result.portfolio_rejected == 1
    assert result.qualified == ()


def test_correlation_gate_rejects_without_position_count_limit():
    existing = Position("P1", "X", PositionSide.LONG, Decimal("100"), Decimal("90"), Decimal("1500"), Decimal("15"), Decimal("1"), status=PositionStatus.OPEN)
    result = OpportunityPipeline(StrategyPipeline(lambda symbol: snapshots(symbol)), lambda symbol: context(positions=[existing], correlation="1")).evaluate(["S"])
    assert result.risk_rejected == 1
    assert result.qualified == ()


def test_final_top_n_is_applied_after_risk_portfolio_gates():
    symbols = [f"S{i}" for i in range(12)]

    def risk_context(symbol: str):
        if symbol == "S0":
            return context(leverage="7", provider="STORM")
        return context()

    result = OpportunityPipeline(StrategyPipeline(lambda symbol: snapshots(symbol)), risk_context).evaluate(symbols, top_n=10)
    assert result.evaluated == 12
    assert result.strategy_qualified == 12
    assert result.risk_rejected == 1
    assert len(result.qualified) == 10
    assert all(item.signal.symbol != "S0" for item in result.qualified)
    assert [item.rank for item in result.qualified] == list(range(1, 11))
    assert len(result.all_evaluations) == 12
    assert sum(item.is_top_10 for item in result.all_evaluations) == 10
    outside_top_ten = next(item for item in result.all_evaluations if item.rank == 11)
    assert outside_top_ten.status == "QUALIFIED"
    assert outside_top_ten.score is not None and outside_top_ten.score >= Decimal("90")
    rejected = next(item for item in result.all_evaluations if item.symbol == "S0")
    assert rejected.gate_stage == "RISK"
    assert rejected.status == "REJECTED"


def test_structural_stop_has_atr_buffer_and_auditable_source():
    result = OpportunityPipeline(
        StrategyPipeline(lambda symbol: snapshots(symbol)), lambda symbol: context()
    ).evaluate(["S"])
    evaluation = result.all_evaluations[0]
    assert evaluation.stop_loss == Decimal("97.50")
    assert evaluation.stop_loss_buffer == Decimal("0.50")
    assert evaluation.stop_loss_source == "LAST_CONFIRMED_SWING_PLUS_ATR_BUFFER"


def test_context_critical_event_blocks_before_risk():
    blocked = ContextAssessment(NewsImpact.NEUTRAL, EventImportance.CRITICAL, ("critical",), True, False, 1.0)
    result = OpportunityPipeline(StrategyPipeline(lambda symbol: snapshots(symbol)), lambda symbol: context(), context_loader=lambda symbol: blocked).evaluate(["S"])
    assert result.strategy_qualified == 1
    assert result.context_rejected == 1
    assert result.risk_rejected == 0
    assert result.qualified == ()


def test_context_high_event_delays_before_risk():
    delayed = ContextAssessment(NewsImpact.NEUTRAL, EventImportance.HIGH, ("high",), False, True, 0.5)
    result = OpportunityPipeline(StrategyPipeline(lambda symbol: snapshots(symbol)), lambda symbol: context(), context_loader=lambda symbol: delayed).evaluate(["S"])
    assert result.context_rejected == 1
    assert result.risk_rejected == 0
    assert result.qualified == ()


def test_one_unavailable_market_does_not_abort_full_scan():
    def loader(symbol: str):
        if symbol == "BAD":
            raise ProviderError("stale candles")
        return snapshots(symbol)

    result = OpportunityPipeline(
        StrategyPipeline(loader), lambda symbol: context()
    ).evaluate(["GOOD", "BAD"])
    assert result.evaluated == 2
    unavailable = next(item for item in result.all_evaluations if item.symbol == "BAD")
    assert unavailable.status == "NO_TRADE"
    assert unavailable.reasons == ("stale candles",)
    assert len(result.qualified) == 1


def test_markets_are_evaluated_concurrently_and_output_order_is_stable():
    started = Barrier(2, timeout=1)

    def loader(symbol: str):
        started.wait()
        raise ProviderError(f"unavailable {symbol}")

    result = OpportunityPipeline(
        StrategyPipeline(loader, max_workers=2), lambda symbol: context()
    ).evaluate(["FIRST", "SECOND"])

    assert [item.symbol for item in result.all_evaluations] == ["FIRST", "SECOND"]
    assert all(item.status == "NO_TRADE" for item in result.all_evaluations)
