from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.market_data import Candle
from app.market.advanced_structure import AdvancedStructureResult, analyze_advanced_structure
from app.market.indicators import IndicatorSnapshot, build_snapshot
from app.market.liquidity import LiquidityResult, analyze_liquidity
from app.market.regime import RegimeResult, classify_regime
from app.market.structure import StructureResult, analyze_structure
from app.market.trend import TrendResult, analyze_trend


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    timeframe: str
    indicators: IndicatorSnapshot
    trend: TrendResult
    structure: StructureResult
    regime: RegimeResult
    liquidity: LiquidityResult
    score: Decimal
    advanced_structure: AdvancedStructureResult | None = None


def analyze_market(symbol: str, timeframe: str, candles: list[Candle]) -> MarketSnapshot:
    trend = analyze_trend(candles)
    structure = analyze_structure(candles)
    advanced = analyze_advanced_structure(candles)
    liquidity = analyze_liquidity(candles)
    return MarketSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        indicators=build_snapshot(candles),
        trend=trend,
        structure=structure,
        regime=classify_regime(candles, trend),
        liquidity=liquidity,
        score=(trend.score + advanced.score + liquidity.score) / Decimal("3"),
        advanced_structure=advanced,
    )
