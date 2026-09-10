from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.market.analysis import MarketSnapshot
from app.strategy.scoring.score import ScoreBreakdown, score_opportunity


HUNDRED = Decimal("100")


def _clamp(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(HUNDRED, value))


def _weighted(quality: Decimal, weight: Decimal) -> Decimal:
    return _clamp(quality) * weight / HUNDRED


@dataclass(frozen=True)
class StrategyEvidence:
    """Normalized factual evidence used to score one strategy opportunity."""

    data_quality: Decimal
    htf_alignment_quality: Decimal
    structure_quality: Decimal
    setup_quality: Decimal
    confirmation_quality: Decimal
    liquidity_quality: Decimal
    volatility_quality: Decimal
    rr_quality: Decimal
    score_breakdown: ScoreBreakdown
    reasons: tuple[str, ...]
    market_regime: str = "UNKNOWN"
    structure_state: str = "UNKNOWN"
    htf_trend: str = "UNKNOWN"


def _indicator_completeness(snapshot: MarketSnapshot) -> Decimal:
    indicators = snapshot.indicators
    base = (
        indicators.ema20,
        indicators.ema50,
        indicators.ema200,
        indicators.rsi14,
        indicators.atr14,
        indicators.volume_sma20,
    )
    base_count = sum(value is not None for value in base)
    if base_count == len(base):
        quality = Decimal("95")
    else:
        quality = Decimal(base_count) / Decimal(len(base)) * Decimal("90")

    extended = (
        indicators.macd_histogram,
        indicators.adx14,
        indicators.supertrend_direction,
        indicators.vwap20,
        indicators.bollinger_middle,
    )
    extended_count = sum(value is not None for value in extended)
    quality += Decimal(extended_count) / Decimal(len(extended)) * Decimal("5")
    return _clamp(quality)


def _data_quality(snapshots: tuple[MarketSnapshot, ...]) -> Decimal:
    total = sum(
        (_indicator_completeness(snapshot) for snapshot in snapshots), Decimal("0")
    )
    return total / Decimal(len(snapshots))


def _htf_alignment(daily: MarketSnapshot, four_hour: MarketSnapshot) -> Decimal:
    if daily.trend.direction != four_hour.trend.direction:
        return Decimal("0")
    if daily.trend.direction not in {"BULLISH", "BEARISH"}:
        return Decimal("0")
    return _clamp((daily.trend.score + four_hour.trend.score) / Decimal("2"))


def _structure_quality(four_hour: MarketSnapshot, one_hour: MarketSnapshot) -> Decimal:
    quality = (four_hour.structure.score * Decimal("0.65")) + (
        one_hour.structure.score * Decimal("0.35")
    )
    advanced = four_hour.advanced_structure
    if advanced is not None:
        quality = max(quality, advanced.score)
    if four_hour.structure.state.startswith("BREAKOUT"):
        quality += Decimal("5")
    elif four_hour.structure.state.startswith("CHOCH"):
        quality += Decimal("2")
    return _clamp(quality)


def _setup_quality(
    setup: str,
    direction: str,
    four_hour: MarketSnapshot,
    one_hour: MarketSnapshot,
    fifteen: MarketSnapshot,
) -> Decimal:
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if setup == "BREAKOUT_RETEST":
        quality = Decimal("90")
        if direction == "LONG" and four_hour.structure.state == "BREAKOUT_UP":
            quality += Decimal("5")
        if direction == "SHORT" and four_hour.structure.state == "BREAKOUT_DOWN":
            quality += Decimal("5")
        return _clamp(quality)
    if setup == "TREND_PULLBACK":
        quality = Decimal("90")
        expected_state = "NEAR_SUPPORT" if direction == "LONG" else "NEAR_RESISTANCE"
        if one_hour.structure.state == expected_state:
            quality += Decimal("5")
        if one_hour.trend.direction == expected:
            quality += Decimal("3")
        return _clamp(quality)
    if setup == "CONTINUATION":
        aligned = sum(
            snapshot.trend.direction == expected
            for snapshot in (four_hour, one_hour, fifteen)
        )
        return _clamp(Decimal("74") + Decimal(aligned) * Decimal("7"))
    return Decimal("0")


def _confirmation_quality(fifteen: MarketSnapshot, direction: str) -> Decimal:
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    bullish = direction == "LONG"
    indicators = fifteen.indicators
    quality = Decimal("0")

    if fifteen.trend.direction == expected:
        quality += Decimal("60")
        if fifteen.trend.score >= Decimal("85"):
            quality += Decimal("10")

    if indicators.rsi14 is not None:
        if (bullish and indicators.rsi14 >= Decimal("50")) or (
            not bullish and indicators.rsi14 <= Decimal("50")
        ):
            quality += Decimal("8")

    if indicators.macd_histogram is not None:
        if (bullish and indicators.macd_histogram > 0) or (
            not bullish and indicators.macd_histogram < 0
        ):
            quality += Decimal("8")

    if indicators.supertrend_direction == expected:
        quality += Decimal("6")

    if indicators.vwap20 is not None and indicators.ema20 is not None:
        if (bullish and indicators.ema20 >= indicators.vwap20) or (
            not bullish and indicators.ema20 <= indicators.vwap20
        ):
            quality += Decimal("4")

    if (
        fifteen.liquidity.volume_ratio is not None
        and fifteen.liquidity.volume_ratio >= Decimal("1")
    ):
        quality += Decimal("4")

    return _clamp(quality)


def _volatility_quality(snapshot: MarketSnapshot) -> Decimal:
    return {
        "NORMAL": Decimal("100"),
        "LOW": Decimal("75"),
        "HIGH": Decimal("50"),
    }.get(snapshot.regime.volatility, Decimal("25"))


def _rr_quality(rr: Decimal) -> Decimal:
    if rr >= Decimal("3"):
        return Decimal("100")
    if rr >= Decimal("2.75"):
        return Decimal("90")
    if rr >= Decimal("2.5"):
        return Decimal("80")
    if rr >= Decimal("2"):
        return Decimal("50")
    return Decimal("0")


def build_strategy_evidence(
    daily: MarketSnapshot,
    four_hour: MarketSnapshot,
    one_hour: MarketSnapshot,
    fifteen: MarketSnapshot,
    *,
    setup: str,
    direction: str,
    rr: Decimal,
) -> StrategyEvidence:
    snapshots = (daily, four_hour, one_hour, fifteen)
    data_quality = _data_quality(snapshots)
    htf_quality = _htf_alignment(daily, four_hour)
    structure_quality = _structure_quality(four_hour, one_hour)
    setup_quality = _setup_quality(setup, direction, four_hour, one_hour, fifteen)
    confirmation_quality = _confirmation_quality(fifteen, direction)
    liquidity_quality = _clamp(fifteen.liquidity.score)
    volatility_quality = _volatility_quality(fifteen)
    rr_quality = _rr_quality(rr)

    breakdown = score_opportunity(
        htf_trend=_weighted(htf_quality, Decimal("20")),
        structure=_weighted(structure_quality, Decimal("15")),
        setup=_weighted(setup_quality, Decimal("25")),
        confirmation=_weighted(confirmation_quality, Decimal("15")),
        liquidity=_weighted(liquidity_quality, Decimal("10")),
        volatility=_weighted(volatility_quality, Decimal("5")),
        rr_quality=_weighted(rr_quality, Decimal("10")),
    )

    reasons = (
        f"data_quality={data_quality:.2f}",
        f"htf_alignment={htf_quality:.2f}",
        f"structure={structure_quality:.2f}",
        f"setup={setup_quality:.2f}",
        f"confirmation={confirmation_quality:.2f}",
        f"liquidity={liquidity_quality:.2f}",
        f"volatility={volatility_quality:.2f}",
        f"rr_quality={rr_quality:.2f}",
    )
    return StrategyEvidence(
        data_quality=data_quality,
        htf_alignment_quality=htf_quality,
        structure_quality=structure_quality,
        setup_quality=setup_quality,
        confirmation_quality=confirmation_quality,
        liquidity_quality=liquidity_quality,
        volatility_quality=volatility_quality,
        rr_quality=rr_quality,
        score_breakdown=breakdown,
        reasons=reasons,
        market_regime=fifteen.regime.regime,
        structure_state=four_hour.structure.state,
        htf_trend=daily.trend.direction,
    )
