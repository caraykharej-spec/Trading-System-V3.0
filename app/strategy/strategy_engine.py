from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.market.analysis import MarketSnapshot
from app.strategy.rules import DEFAULT_RULES, StrategyRules
from app.strategy.scoring.confidence import ConfidenceResult, calculate_confidence
from app.strategy.scoring.score import ScoreBreakdown, score_opportunity
from app.strategy.targets.risk_reward import RiskReward, calculate_risk_reward


class StrategyState(str, Enum):
    NO_TRADE = "NO_TRADE"
    WAIT = "WAIT"
    SETUP_DETECTED = "SETUP_DETECTED"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    READY_FOR_RISK_REVIEW = "READY_FOR_RISK_REVIEW"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class StrategySignal:
    symbol: str
    direction: str
    setup: str
    state: StrategyState
    entry: Decimal
    stop_loss: Decimal
    target: Decimal
    rr: Decimal
    score: Decimal
    confidence: Decimal
    score_breakdown: ScoreBreakdown
    confidence_result: ConfidenceResult
    reasons: tuple[str, ...]


def _direction(daily: MarketSnapshot, four_hour: MarketSnapshot) -> str | None:
    if daily.trend.direction != four_hour.trend.direction:
        return None
    if daily.trend.direction not in {"BULLISH", "BEARISH"}:
        return None
    return "LONG" if daily.trend.direction == "BULLISH" else "SHORT"


def _levels(four_hour: MarketSnapshot, one_hour: MarketSnapshot, fifteen: MarketSnapshot, direction: str) -> tuple[Decimal, Decimal, Decimal] | None:
    entry = fifteen.indicators.ema20 or one_hour.indicators.ema20
    support = four_hour.structure.support
    resistance = four_hour.structure.resistance
    if entry is None:
        return None
    if direction == "LONG":
        if support is None or resistance is None or support >= entry or resistance <= entry:
            return None
        risk = entry - support
        target = entry + risk * Decimal("2.5")
        return entry, support, target
    if support is None or resistance is None or resistance <= entry or support >= entry:
        return None
    risk = resistance - entry
    target = entry - risk * Decimal("2.5")
    return entry, resistance, target


def detect_setup(four_hour: MarketSnapshot, one_hour: MarketSnapshot, fifteen: MarketSnapshot, direction: str) -> str | None:
    """Primary setups only: breakout-retest, trend-pullback, continuation."""
    if direction == "LONG":
        if four_hour.structure.breakout_up and one_hour.structure.near_resistance:
            return "BREAKOUT_RETEST"
        if one_hour.trend.direction == "BULLISH" and one_hour.structure.near_support:
            return "TREND_PULLBACK"
        if four_hour.trend.direction == "BULLISH" and one_hour.trend.direction == "BULLISH" and fifteen.trend.direction == "BULLISH":
            return "CONTINUATION"
    else:
        if four_hour.structure.breakout_down and one_hour.structure.near_support:
            return "BREAKOUT_RETEST"
        if one_hour.trend.direction == "BEARISH" and one_hour.structure.near_resistance:
            return "TREND_PULLBACK"
        if four_hour.trend.direction == "BEARISH" and one_hour.trend.direction == "BEARISH" and fifteen.trend.direction == "BEARISH":
            return "CONTINUATION"
    return None


def evaluate_strategy(daily: MarketSnapshot, four_hour: MarketSnapshot, one_hour: MarketSnapshot, fifteen: MarketSnapshot, *, rules: StrategyRules = DEFAULT_RULES) -> StrategySignal:
    direction = _direction(daily, four_hour)
    if direction is None:
        raise ValueError("No aligned HTF direction")
    setup = detect_setup(four_hour, one_hour, fifteen, direction)
    if setup is None:
        raise ValueError("No approved setup")
    levels = _levels(four_hour, one_hour, fifteen, direction)
    if levels is None:
        raise ValueError("No valid entry/SL/target levels")
    entry, stop_loss, target = levels
    rr: RiskReward = calculate_risk_reward(entry, stop_loss, target, direction)
    confirmation = Decimal("100") if fifteen.trend.direction == ("BULLISH" if direction == "LONG" else "BEARISH") else Decimal("50")
    sb = score_opportunity(
        htf_trend=Decimal("20"),
        structure=Decimal("15"),
        setup=Decimal("25"),
        confirmation=Decimal("15") if confirmation == 100 else Decimal("7.5"),
        liquidity=min(Decimal("10"), fifteen.liquidity.score / Decimal("10")),
        volatility=Decimal("5") if fifteen.regime.volatility != "HIGH" else Decimal("2.5"),
        rr_quality=Decimal("10") if rr.ratio >= Decimal("3") else Decimal("8"),
    )
    confidence_result = calculate_confidence(data_quality=100, htf_alignment=100, structure_quality=90, confirmation_quality=confirmation)
    reasons: list[str] = []
    if rr.ratio < rules.min_rr:
        reasons.append("R:R below minimum")
    if sb.total < rules.min_score:
        reasons.append("score below minimum")
    if confidence_result.value < rules.min_confidence:
        reasons.append("confidence below minimum")
    state = StrategyState.READY_FOR_RISK_REVIEW if not reasons else StrategyState.REJECTED
    return StrategySignal(daily.symbol, direction, setup, state, entry, stop_loss, target, rr.ratio, sb.total, confidence_result.value, sb, confidence_result, tuple(reasons))
