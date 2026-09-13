from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import overload

from app.data.market_data import Candle
from app.market.advanced_structure import (
    AdvancedStructureResult,
    StructureBreak,
    SwingPoint,
)
from app.market.analysis import MarketSnapshot
from app.market.indicators import IndicatorSnapshot
from app.market.liquidity import analyze_liquidity
from app.market.regime import classify_regime
from app.market.structure import analyze_structure
from app.market.trend import TrendResult

_TIMEFRAME_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}
_TIMEFRAME_ORDER = ("1d", "4h", "1h", "15m")
_MAX_RECENT_CANDLES = 21
_MAX_RECENT_CLOSES = 50


@dataclass
class _EmaState:
    period: int
    count: int = 0
    seed_sum: Decimal = Decimal("0")
    value: Decimal | None = None

    def push(self, item: Decimal) -> Decimal | None:
        self.count += 1
        if self.count <= self.period:
            self.seed_sum += item
            if self.count == self.period:
                self.value = self.seed_sum / Decimal(self.period)
            return self.value
        if self.value is None:
            raise RuntimeError("EMA state is uninitialized")
        multiplier = Decimal(2) / Decimal(self.period + 1)
        self.value = (item - self.value) * multiplier + self.value
        return self.value


class _SwingHistoryView(Sequence[SwingPoint]):
    """Immutable prefix view over an append-only swing list.

    Creating a historical snapshot is O(1): the view freezes the visible length
    without copying the accumulated swing history. Later appends to the backing
    list are not visible through earlier views.
    """

    __slots__ = ("_items", "_length")

    def __init__(self, items: list[SwingPoint], length: int) -> None:
        if length < 0 or length > len(items):
            raise ValueError("invalid swing history prefix length")
        self._items = items
        self._length = length

    def __len__(self) -> int:
        return self._length

    @overload
    def __getitem__(self, index: int) -> SwingPoint: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[SwingPoint]: ...

    def __getitem__(self, index: int | slice) -> SwingPoint | Sequence[SwingPoint]:
        if isinstance(index, slice):
            start, stop, step = index.indices(self._length)
            return tuple(self._items[position] for position in range(start, stop, step))
        normalized = index + self._length if index < 0 else index
        if normalized < 0 or normalized >= self._length:
            raise IndexError("swing history index out of range")
        return self._items[normalized]


class IncrementalMarketState:
    """Exact incremental equivalent of analyze_market for chronological candles.

    All indicator work is constant or bounded-window per candle. Only confirmed
    swing points are retained long-term because they are part of strategy evidence.
    """

    def __init__(self, symbol: str, timeframe: str) -> None:
        if timeframe not in _TIMEFRAME_MINUTES:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        self.symbol = symbol
        self.timeframe = timeframe
        self._count = 0
        self._last_timestamp: datetime | None = None
        self._recent_candles: deque[Candle] = deque(maxlen=_MAX_RECENT_CANDLES)
        self._recent_closes: deque[Decimal] = deque(maxlen=_MAX_RECENT_CLOSES)
        self._ema12 = _EmaState(12)
        self._ema20 = _EmaState(20)
        self._ema26 = _EmaState(26)
        self._ema50 = _EmaState(50)
        self._ema200 = _EmaState(200)
        self._macd_signal = _EmaState(9)
        self._macd_line: Decimal | None = None
        self._macd_signal_value: Decimal | None = None
        self._swing_highs: list[SwingPoint] = []
        self._swing_lows: list[SwingPoint] = []
        self._latest: MarketSnapshot | None = None

    @property
    def count(self) -> int:
        return self._count

    @property
    def latest(self) -> MarketSnapshot | None:
        return self._latest

    def push(self, candle: Candle) -> MarketSnapshot:
        if candle.symbol != self.symbol or candle.timeframe != self.timeframe:
            raise ValueError("candle identity does not match incremental market state")
        if self._last_timestamp is not None:
            if candle.timestamp == self._last_timestamp:
                raise ValueError("duplicate candle timestamps")
            if candle.timestamp < self._last_timestamp:
                raise ValueError("candles must be chronological")

        self._count += 1
        self._last_timestamp = candle.timestamp
        self._recent_candles.append(candle)
        self._recent_closes.append(candle.close)

        fast = self._ema12.push(candle.close)
        ema20 = self._ema20.push(candle.close)
        slow = self._ema26.push(candle.close)
        ema50 = self._ema50.push(candle.close)
        ema200 = self._ema200.push(candle.close)

        if fast is not None and slow is not None:
            current_macd = fast - slow
            current_signal = self._macd_signal.push(current_macd)
            if current_signal is not None:
                self._macd_line = current_macd
                self._macd_signal_value = current_signal

        self._update_swings()
        indicators = self._indicator_snapshot(ema20, ema50, ema200)
        trend = self._trend(indicators)
        advanced = self._advanced_structure()
        recent = list(self._recent_candles)
        structure = analyze_structure(recent[-20:])
        liquidity = analyze_liquidity(recent[-21:])
        regime = classify_regime(recent[-20:], trend)
        self._latest = MarketSnapshot(
            symbol=self.symbol,
            timeframe=self.timeframe,
            indicators=indicators,
            trend=trend,
            structure=structure,
            regime=regime,
            liquidity=liquidity,
            score=(trend.score + advanced.score + liquidity.score) / Decimal("3"),
            advanced_structure=advanced,
        )
        return self._latest

    def _indicator_snapshot(
        self,
        ema20: Decimal | None,
        ema50: Decimal | None,
        ema200: Decimal | None,
    ) -> IndicatorSnapshot:
        closes = list(self._recent_closes)
        recent = list(self._recent_candles)
        last20 = recent[-20:]
        last50 = closes[-50:]

        rsi14 = self._rsi(closes[-15:])
        atr14 = self._atr(recent)
        volume_sma20 = (
            sum((item.volume for item in last20), Decimal("0")) / Decimal("20")
            if len(last20) == 20
            else None
        )
        sma50 = (
            sum(last50, Decimal("0")) / Decimal("50") if len(last50) == 50 else None
        )
        adx14 = self._adx(recent)
        vwap20 = self._vwap(last20)
        middle, upper, lower = self._bollinger(last20)

        supertrend: str | None = None
        if atr14 is not None and ema20 is not None and ema50 is not None:
            latest = recent[-1]
            midpoint = (latest.high + latest.low) / Decimal("2")
            upper_band = midpoint + Decimal("3") * atr14
            lower_band = midpoint - Decimal("3") * atr14
            if latest.close >= lower_band and ema20 > ema50:
                supertrend = "BULLISH"
            elif latest.close <= upper_band and ema20 < ema50:
                supertrend = "BEARISH"
            else:
                supertrend = "NEUTRAL"

        macd_line = self._macd_line
        macd_signal = self._macd_signal_value
        macd_histogram = (
            macd_line - macd_signal
            if macd_line is not None and macd_signal is not None
            else None
        )
        return IndicatorSnapshot(
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            rsi14=rsi14,
            atr14=atr14,
            volume_sma20=volume_sma20,
            sma50=sma50,
            macd_line=macd_line,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            adx14=adx14,
            supertrend_direction=supertrend,
            vwap20=vwap20,
            bollinger_middle=middle,
            bollinger_upper=upper,
            bollinger_lower=lower,
        )

    @staticmethod
    def _rsi(closes: list[Decimal], period: int = 14) -> Decimal | None:
        if len(closes) < period + 1:
            return None
        gains: list[Decimal] = []
        losses: list[Decimal] = []
        for previous, current in zip(closes[-period - 1 : -1], closes[-period:]):
            change = current - previous
            gains.append(max(change, Decimal("0")))
            losses.append(max(-change, Decimal("0")))
        avg_gain = sum(gains, Decimal("0")) / Decimal(period)
        avg_loss = sum(losses, Decimal("0")) / Decimal(period)
        if avg_loss == 0:
            return Decimal("100") if avg_gain > 0 else Decimal("50")
        rs = avg_gain / avg_loss
        return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))

    @staticmethod
    def _true_range(previous: Candle, current: Candle) -> Decimal:
        return max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )

    @classmethod
    def _atr(cls, candles: list[Candle], period: int = 14) -> Decimal | None:
        if len(candles) < period + 1:
            return None
        pairs = zip(candles[-period - 1 : -1], candles[-period:])
        ranges = [cls._true_range(previous, current) for previous, current in pairs]
        return sum(ranges, Decimal("0")) / Decimal(period)

    @classmethod
    def _adx(cls, candles: list[Candle], period: int = 14) -> Decimal | None:
        if len(candles) < period + 2:
            return None
        pairs = list(zip(candles[-period - 1 : -1], candles[-period:]))
        plus_dm: list[Decimal] = []
        minus_dm: list[Decimal] = []
        ranges: list[Decimal] = []
        for previous, current in pairs:
            up_move = current.high - previous.high
            down_move = previous.low - current.low
            plus_dm.append(
                up_move if up_move > down_move and up_move > 0 else Decimal("0")
            )
            minus_dm.append(
                down_move if down_move > up_move and down_move > 0 else Decimal("0")
            )
            ranges.append(cls._true_range(previous, current))
        total_range = sum(ranges, Decimal("0"))
        if total_range <= 0:
            return Decimal("0")
        plus_di = Decimal("100") * sum(plus_dm, Decimal("0")) / total_range
        minus_di = Decimal("100") * sum(minus_dm, Decimal("0")) / total_range
        denominator = plus_di + minus_di
        if denominator <= 0:
            return Decimal("0")
        return Decimal("100") * abs(plus_di - minus_di) / denominator

    @staticmethod
    def _vwap(candles: list[Candle]) -> Decimal | None:
        if len(candles) < 20:
            return None
        total_volume = sum((item.volume for item in candles[-20:]), Decimal("0"))
        if total_volume <= 0:
            return None
        weighted = sum(
            (
                ((item.high + item.low + item.close) / Decimal("3")) * item.volume
                for item in candles[-20:]
            ),
            Decimal("0"),
        )
        return weighted / total_volume

    @staticmethod
    def _bollinger(
        candles: list[Candle],
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        if len(candles) < 20:
            return None, None, None
        values = [item.close for item in candles[-20:]]
        middle = sum(values, Decimal("0")) / Decimal("20")
        variance = (
            sum(((value - middle) ** 2 for value in values), Decimal("0"))
            / Decimal("20")
        )
        deviation = variance.sqrt()
        return (
            middle,
            middle + Decimal("2") * deviation,
            middle - Decimal("2") * deviation,
        )

    def _trend(self, indicators: IndicatorSnapshot) -> TrendResult:
        last = self._recent_candles[-1].close
        if (
            indicators.ema20 is None
            or indicators.ema50 is None
            or indicators.ema200 is None
        ):
            return TrendResult("UNKNOWN", "UNKNOWN", Decimal("0"), indicators)
        if last > indicators.ema20 > indicators.ema50 > indicators.ema200:
            direction = "BULLISH"
        elif last < indicators.ema20 < indicators.ema50 < indicators.ema200:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        if direction == "NEUTRAL":
            return TrendResult(direction, "WEAK", Decimal("45"), indicators)

        score = Decimal("60")
        bullish = direction == "BULLISH"
        if indicators.rsi14 is not None:
            if (bullish and indicators.rsi14 >= Decimal("50")) or (
                not bullish and indicators.rsi14 <= Decimal("50")
            ):
                score += Decimal("10")
        if indicators.macd_histogram is not None:
            if (bullish and indicators.macd_histogram > 0) or (
                not bullish and indicators.macd_histogram < 0
            ):
                score += Decimal("10")
        if indicators.adx14 is not None:
            if indicators.adx14 >= Decimal("25"):
                score += Decimal("10")
            elif indicators.adx14 >= Decimal("18"):
                score += Decimal("5")
        if indicators.supertrend_direction == direction:
            score += Decimal("5")
        if indicators.vwap20 is not None:
            if (bullish and last >= indicators.vwap20) or (
                not bullish and last <= indicators.vwap20
            ):
                score += Decimal("5")

        score = min(score, Decimal("100"))
        strength = "STRONG" if score >= 85 else "MODERATE" if score >= 65 else "WEAK"
        return TrendResult(direction, strength, score, indicators)

    def _update_swings(self, pivot: int = 2) -> None:
        if self._count < pivot * 2 + 1:
            return
        window = list(self._recent_candles)[-(pivot * 2 + 1) :]
        current = window[pivot]
        left = window[:pivot]
        right = window[pivot + 1 :]
        index = self._count - pivot - 1
        if current.high > max(item.high for item in left) and current.high >= max(
            item.high for item in right
        ):
            self._swing_highs.append(
                SwingPoint("HIGH", current.timestamp, current.high, index)
            )
        if current.low < min(item.low for item in left) and current.low <= min(
            item.low for item in right
        ):
            self._swing_lows.append(SwingPoint("LOW", current.timestamp, current.low, index))

    def _advanced_structure(self) -> AdvancedStructureResult:
        highs = _SwingHistoryView(self._swing_highs, len(self._swing_highs))
        lows = _SwingHistoryView(self._swing_lows, len(self._swing_lows))
        if len(highs) < 2 or len(lows) < 2:
            trend = "UNKNOWN"
        else:
            higher_high = highs[-1].price > highs[-2].price
            higher_low = lows[-1].price > lows[-2].price
            lower_high = highs[-1].price < highs[-2].price
            lower_low = lows[-1].price < lows[-2].price
            if higher_high and higher_low:
                trend = "BULLISH"
            elif lower_high and lower_low:
                trend = "BEARISH"
            else:
                trend = "TRANSITION"

        if not highs or not lows:
            return AdvancedStructureResult(
                highs,
                lows,
                trend,
                "UNKNOWN",
                None,
                lows[-1].price if lows else None,
                highs[-1].price if highs else None,
                Decimal("0"),
            )

        last = self._recent_candles[-1]
        last_high = highs[-1]
        last_low = lows[-1]
        break_event: StructureBreak | None = None
        structure = "RANGE"
        if last.close > last_high.price:
            kind = "BOS" if trend == "BULLISH" else "CHOCH"
            break_event = StructureBreak("UP", kind, last_high.price, last.timestamp)
            structure = kind
        elif last.close < last_low.price:
            kind = "BOS" if trend == "BEARISH" else "CHOCH"
            break_event = StructureBreak("DOWN", kind, last_low.price, last.timestamp)
            structure = kind
        elif trend == "BULLISH":
            structure = "HIGHER_HIGH_HIGHER_LOW"
        elif trend == "BEARISH":
            structure = "LOWER_HIGH_LOWER_LOW"
        else:
            structure = "TRANSITION"

        score = (
            Decimal("90")
            if structure == "BOS"
            else Decimal("85")
            if structure == "CHOCH"
            else Decimal("70")
            if trend in {"BULLISH", "BEARISH"}
            else Decimal("50")
        )
        return AdvancedStructureResult(
            highs,
            lows,
            trend,
            structure,
            break_event,
            last_low.price,
            last_high.price,
            score,
        )


class IncrementalSnapshotCursor:
    """Advance each timeframe only when a candle is completed at decision time."""

    def __init__(
        self,
        symbol: str,
        candles_by_timeframe: dict[str, list[Candle]],
    ) -> None:
        self.symbol = symbol
        self._candles = candles_by_timeframe
        self._next_index = {timeframe: 0 for timeframe in _TIMEFRAME_ORDER}
        self._states = {
            timeframe: IncrementalMarketState(symbol, timeframe)
            for timeframe in _TIMEFRAME_ORDER
        }
        self._last_decision_time: datetime | None = None

    def _reset(self) -> None:
        self._next_index = {timeframe: 0 for timeframe in _TIMEFRAME_ORDER}
        self._states = {
            timeframe: IncrementalMarketState(self.symbol, timeframe)
            for timeframe in _TIMEFRAME_ORDER
        }

    def snapshots_at(
        self,
        decision_time: datetime,
    ) -> dict[str, MarketSnapshot] | None:
        if (
            self._last_decision_time is not None
            and decision_time < self._last_decision_time
        ):
            self._reset()
        self._last_decision_time = decision_time
        snapshots: dict[str, MarketSnapshot] = {}
        for timeframe in _TIMEFRAME_ORDER:
            duration = timedelta(minutes=_TIMEFRAME_MINUTES[timeframe])
            rows = self._candles[timeframe]
            index = self._next_index[timeframe]
            state = self._states[timeframe]
            while index < len(rows) and rows[index].timestamp + duration <= decision_time:
                state.push(rows[index])
                index += 1
            self._next_index[timeframe] = index
            if state.count < 2 or state.latest is None:
                return None
            snapshots[timeframe] = state.latest
        return snapshots
