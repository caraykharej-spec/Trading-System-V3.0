from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.market_data import Candle


@dataclass(frozen=True)
class IndicatorSnapshot:
    ema20: Decimal | None
    ema50: Decimal | None
    ema200: Decimal | None
    rsi14: Decimal | None
    atr14: Decimal | None
    volume_sma20: Decimal | None
    sma50: Decimal | None = None
    macd_line: Decimal | None = None
    macd_signal: Decimal | None = None
    macd_histogram: Decimal | None = None
    adx14: Decimal | None = None
    supertrend_direction: str | None = None
    vwap20: Decimal | None = None
    bollinger_middle: Decimal | None = None
    bollinger_upper: Decimal | None = None
    bollinger_lower: Decimal | None = None


def _ordered(candles: list[Candle]) -> list[Candle]:
    return sorted(candles, key=lambda candle: candle.timestamp)


def _closes(candles: list[Candle]) -> list[Decimal]:
    return [candle.close for candle in _ordered(candles)]


def sma(values: list[Decimal], period: int) -> Decimal | None:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return None
    return sum(values[-period:], Decimal("0")) / Decimal(period)


def ema(values: list[Decimal], period: int) -> Decimal | None:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return None
    multiplier = Decimal(2) / Decimal(period + 1)
    result = sum(values[:period], Decimal("0")) / Decimal(period)
    for value in values[period:]:
        result = (value - result) * multiplier + result
    return result


def _ema_series(values: list[Decimal], period: int) -> list[Decimal]:
    if len(values) < period:
        return []
    multiplier = Decimal(2) / Decimal(period + 1)
    current = sum(values[:period], Decimal("0")) / Decimal(period)
    series = [current]
    for value in values[period:]:
        current = (value - current) * multiplier + current
        series.append(current)
    return series


def rsi(values: list[Decimal], period: int = 14) -> Decimal | None:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period + 1:
        return None
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for previous, current in zip(values[-period - 1 : -1], values[-period:]):
        change = current - previous
        gains.append(max(change, Decimal("0")))
        losses.append(max(-change, Decimal("0")))
    avg_gain = sum(gains, Decimal("0")) / Decimal(period)
    avg_loss = sum(losses, Decimal("0")) / Decimal(period)
    if avg_loss == 0:
        return Decimal("100") if avg_gain > 0 else Decimal("50")
    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def true_ranges(candles: list[Candle]) -> list[Decimal]:
    ordered = _ordered(candles)
    values: list[Decimal] = []
    for previous, current in zip(ordered[:-1], ordered[1:]):
        values.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return values


def atr(candles: list[Candle], period: int = 14) -> Decimal | None:
    ranges = true_ranges(candles)
    if len(ranges) < period:
        return None
    return sum(ranges[-period:], Decimal("0")) / Decimal(period)


def macd(
    values: list[Decimal], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if fast <= 0 or slow <= fast or signal <= 0 or len(values) < slow + signal - 1:
        return None, None, None
    fast_series = _ema_series(values, fast)
    slow_series = _ema_series(values, slow)
    offset = slow - fast
    aligned_fast = fast_series[offset:]
    macd_series = [fast_value - slow_value for fast_value, slow_value in zip(aligned_fast, slow_series)]
    signal_value = ema(macd_series, signal)
    if not macd_series or signal_value is None:
        return None, None, None
    line = macd_series[-1]
    return line, signal_value, line - signal_value


def adx(candles: list[Candle], period: int = 14) -> Decimal | None:
    ordered = _ordered(candles)
    if period <= 0 or len(ordered) < period + 2:
        return None
    plus_dm: list[Decimal] = []
    minus_dm: list[Decimal] = []
    ranges: list[Decimal] = []
    for previous, current in zip(ordered[:-1], ordered[1:]):
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else Decimal("0"))
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else Decimal("0"))
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    if len(ranges) < period:
        return None
    tr = sum(ranges[-period:], Decimal("0"))
    if tr <= 0:
        return Decimal("0")
    plus_di = Decimal("100") * sum(plus_dm[-period:], Decimal("0")) / tr
    minus_di = Decimal("100") * sum(minus_dm[-period:], Decimal("0")) / tr
    denominator = plus_di + minus_di
    if denominator <= 0:
        return Decimal("0")
    return Decimal("100") * abs(plus_di - minus_di) / denominator


def vwap(candles: list[Candle], period: int = 20) -> Decimal | None:
    ordered = _ordered(candles)
    if len(ordered) < period:
        return None
    window = ordered[-period:]
    total_volume = sum((candle.volume for candle in window), Decimal("0"))
    if total_volume <= 0:
        return None
    weighted = sum(
        (((candle.high + candle.low + candle.close) / Decimal("3")) * candle.volume for candle in window),
        Decimal("0"),
    )
    return weighted / total_volume


def bollinger(
    values: list[Decimal], period: int = 20, deviations: Decimal = Decimal("2")
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    middle = sma(values, period)
    if middle is None:
        return None, None, None
    window = values[-period:]
    variance = sum(((value - middle) ** 2 for value in window), Decimal("0")) / Decimal(period)
    standard_deviation = variance.sqrt()
    return middle, middle + deviations * standard_deviation, middle - deviations * standard_deviation


def supertrend_direction(candles: list[Candle], period: int = 14) -> str | None:
    ordered = _ordered(candles)
    current_atr = atr(ordered, period)
    if current_atr is None or not ordered:
        return None
    latest = ordered[-1]
    midpoint = (latest.high + latest.low) / Decimal("2")
    upper = midpoint + Decimal("3") * current_atr
    lower = midpoint - Decimal("3") * current_atr
    ema20 = ema([candle.close for candle in ordered], 20)
    ema50 = ema([candle.close for candle in ordered], 50)
    if ema20 is None or ema50 is None:
        return None
    if latest.close >= lower and ema20 > ema50:
        return "BULLISH"
    if latest.close <= upper and ema20 < ema50:
        return "BEARISH"
    return "NEUTRAL"


def build_snapshot(candles: list[Candle]) -> IndicatorSnapshot:
    ordered = _ordered(candles)
    closes = [candle.close for candle in ordered]
    volumes = [candle.volume for candle in ordered[-20:]]
    line, signal, histogram = macd(closes)
    bb_middle, bb_upper, bb_lower = bollinger(closes)
    return IndicatorSnapshot(
        ema20=ema(closes, 20),
        ema50=ema(closes, 50),
        ema200=ema(closes, 200),
        rsi14=rsi(closes),
        atr14=atr(ordered),
        volume_sma20=(
            sum(volumes, Decimal("0")) / Decimal("20") if len(volumes) == 20 else None
        ),
        sma50=sma(closes, 50),
        macd_line=line,
        macd_signal=signal,
        macd_histogram=histogram,
        adx14=adx(ordered),
        supertrend_direction=supertrend_direction(ordered),
        vwap20=vwap(ordered),
        bollinger_middle=bb_middle,
        bollinger_upper=bb_upper,
        bollinger_lower=bb_lower,
    )
