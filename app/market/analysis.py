from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.market_data import Candle
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


def analyze_market(symbol: str, timeframe: str, candles: list[Candle]) -> MarketSnapshot:
    trend = analyze_trend(candles)
    return MarketSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        indicators=build_snapshot(candles),
        trend=trend,
        structure=analyze_structure(candles),
        regime=classify_regime(candles, trend),
        liquidity=analyze_liquidity(candles),
        score=(trend.score + analyze_structure(candles).score + analyze_liquidity(candles).score) / Decimal("3"),
    )
