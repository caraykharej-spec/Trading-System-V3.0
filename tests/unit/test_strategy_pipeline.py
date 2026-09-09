from decimal import Decimal

from app.application.strategy_pipeline import StrategyPipeline
from app.market.analysis import MarketSnapshot
from app.market.indicators import IndicatorSnapshot
from app.market.liquidity import LiquidityResult
from app.market.regime import RegimeResult
from app.market.structure import StructureResult
from app.market.trend import TrendResult


def snapshot(symbol: str, timeframe: str, direction: str) -> MarketSnapshot:
    indicators = IndicatorSnapshot(Decimal("100"), Decimal("99"), Decimal("95"), Decimal("55"), Decimal("2"), Decimal("100"))
    return MarketSnapshot(symbol, timeframe, indicators, TrendResult(direction, "STRONG", Decimal("100"), indicators), StructureResult(Decimal("98"), Decimal("102"), False, False, False, False, Decimal("100")), RegimeResult("TRENDING_BULL" if direction == "BULLISH" else "TRENDING_BEAR", "NORMAL", Decimal("100")), LiquidityResult(Decimal("100"), Decimal("100"), Decimal("1"), Decimal("100")), Decimal("100"))


def loader(symbol: str):
    return tuple(snapshot(symbol, tf, "BULLISH") for tf in ("1D", "4H", "1H", "15M"))


def test_pipeline_ranks_and_limits_to_top_ten():
    result = StrategyPipeline(loader).evaluate([f"S{i}" for i in range(12)])
    assert result.evaluated == 12
    assert len(result.qualified) <= 10
    assert [item.rank for item in result.qualified] == list(range(1, len(result.qualified) + 1))


def test_pipeline_skips_invalid_symbol():
    def load(symbol: str):
        if symbol == "BAD":
            raise ValueError("insufficient data")
        return loader(symbol)

    result = StrategyPipeline(load).evaluate(["BAD", "GOOD"])
    assert result.evaluated == 2
    assert len(result.qualified) == 1
    assert result.qualified[0].signal.symbol == "GOOD"
