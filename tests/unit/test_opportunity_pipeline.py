from decimal import Decimal

from app.application.opportunity_pipeline import OpportunityPipeline, RiskContext
from app.application.strategy_pipeline import StrategyPipeline
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
