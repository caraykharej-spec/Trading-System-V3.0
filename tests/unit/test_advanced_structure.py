from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.data.market_data import Candle
from app.market.advanced_structure import analyze_advanced_structure, detect_swings


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def c(i: int, high: str, low: str, close: str) -> Candle:
    return Candle("TEST/USDT", "1h", START + timedelta(hours=i), Decimal(close), Decimal(high), Decimal(low), Decimal(close), Decimal("100"))


def test_detects_higher_highs_and_higher_lows():
    candles = [c(i, str(v + 2), str(v - 2), str(v)) for i, v in enumerate([100, 101, 105, 102, 108, 104, 112, 109, 115])]
    result = analyze_advanced_structure(candles, pivot=1)
    assert result.trend == "BULLISH"
    assert result.structure in {"HIGHER_HIGH_HIGHER_LOW", "BOS"}
    assert result.support is not None and result.resistance is not None


def test_detects_bearish_sequence():
    candles = [c(i, str(v + 2), str(v - 2), str(v)) for i, v in enumerate([115, 112, 108, 111, 105, 109, 102, 106, 99])]
    result = analyze_advanced_structure(candles, pivot=1)
    assert result.trend == "BEARISH"
    assert result.structure in {"LOWER_HIGH_LOWER_LOW", "BOS"}


def test_detects_transition_when_sequences_disagree():
    candles = [c(i, str(v + 2), str(v - 2), str(v)) for i, v in enumerate([100, 105, 102, 108, 103, 106, 104])]
    result = analyze_advanced_structure(candles, pivot=1)
    assert result.trend == "TRANSITION"


def test_detects_bos_after_bullish_structure():
    values = [100, 102, 106, 103, 109, 105, 112, 110, 116]
    candles = [c(i, str(v + 1), str(v - 1), str(v)) for i, v in enumerate(values)]
    result = analyze_advanced_structure(candles, pivot=1)
    assert result.structure in {"HIGHER_HIGH_HIGHER_LOW", "BOS"}


def test_duplicate_timestamp_is_rejected():
    candles = [c(0, "101", "99", "100"), c(0, "102", "98", "101")]
    with pytest.raises(ValueError, match="duplicate"):
        detect_swings(candles)


def test_insufficient_history_is_safe():
    result = analyze_advanced_structure([c(0, "101", "99", "100"), c(1, "102", "98", "101")], pivot=2)
    assert result.trend == "UNKNOWN"
    assert result.structure == "UNKNOWN"
