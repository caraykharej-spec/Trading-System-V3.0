from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.market.analysis import MarketSnapshot
from app.strategy.evidence import StrategyEvidence, build_strategy_evidence
from app.strategy.rules import DEFAULT_RULES, StrategyRules
from app.strategy.scoring.confidence import ConfidenceResult, calculate_confidence
from app.strategy.scoring.score import ScoreBreakdown
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
    evidence: StrategyEvidence | None = None


def _direction(daily: MarketSnapshot, four_hour: MarketSnapshot) -> str | None:
    if daily.trend.direction != four_hour.trend.direction:
        return None
    if daily.trend.direction not in {"BULLISH", "BEARISH"}:
        return None
    return "LONG" if daily.trend.direction == "BULLISH" else "SHORT"


def _levels(
    four_hour: MarketSnapshot,
    one_hour: MarketSnapshot,
    fifteen: MarketSnapshot,
    direction: str,
) -> tuple[Decimal, Decimal, Decimal] | None:
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


def detect_setup(
    four_hour: MarketSnapshot,
    one_hour: MarketSnapshot,
    fifteen: MarketSnapshot,
    direction: str,
) -> str | None:
    """Detect approved price-action setups without changing structural invalidation."""
    four_state = four_hour.structure.state
    one_state = one_hour.structure.state
    if direction == "LONG":
        if four_state == "BREAKOUT_UP" and one_state == "NEAR_RESISTANCE":
            return "BREAKOUT_RETEST"
        if one_hour.trend.direction == "BULLISH" and one_state == "NEAR_SUPPORT":
            return "TREND_PULLBACK"
        if (
            four_hour.trend.direction == "BULLISH"
            and one_hour.trend.direction == "BULLISH"
            and fifteen.trend.direction == "BULLISH"
        ):
            return "CONTINUATION"
    else:
        if four_state == "BREAKOUT_DOWN" and one_state == "NEAR_SUPPORT":
            return "BREAKOUT_RETEST"
        if one_hour.trend.direction == "BEARISH" and one_state == "NEAR_RESISTANCE":
            return "TREND_PULLBACK"
        if (
            four_hour.trend.direction == "BEARISH"
            and one_hour.trend.direction == "BEARISH"
            and fifteen.trend.direction == "BEARISH"
        ):
            return "CONTINUATION"
    return None


def evaluate_strategy(
    daily: MarketSnapshot,
    four_hour: MarketSnapshot,
    one_hour: MarketSnapshot,
    fifteen: MarketSnapshot,
    *,
    rules: StrategyRules = DEFAULT_RULES,
) -> StrategySignal:
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
    evidence = build_strategy_evidence(
        daily,
        four_hour,
        one_hour,
        fifteen,
        setup=setup,
        direction=direction,
        rr=rr.ratio,
    )
    score_breakdown = evidence.score_breakdown
    confidence_result = calculate_confidence(
        data_quality=evidence.data_quality,
        htf_alignment=evidence.htf_alignment_quality,
        structure_quality=evidence.structure_quality,
        confirmation_quality=evidence.confirmation_quality,
    )

    reasons: list[str] = []
    if rr.ratio < rules.min_rr:
        reasons.append("R:R below minimum")
    if score_breakdown.total < rules.min_score:
        reasons.append("score below minimum")
    if confidence_result.value < rules.min_confidence:
        reasons.append("confidence below minimum")
    state = StrategyState.READY_FOR_RISK_REVIEW if not reasons else StrategyState.REJECTED
    return StrategySignal(
        symbol=daily.symbol,
        direction=direction,
        setup=setup,
        state=state,
        entry=entry,
        stop_loss=stop_loss,
        target=target,
        rr=rr.ratio,
        score=score_breakdown.total,
        confidence=confidence_result.value,
        score_breakdown=score_breakdown,
        confidence_result=confidence_result,
        reasons=tuple(reasons),
        evidence=evidence,
    )
