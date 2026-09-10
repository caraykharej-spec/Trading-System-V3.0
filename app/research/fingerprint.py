from __future__ import annotations

from datetime import timezone
from decimal import Decimal
import hashlib
import json

from app.data.market_data import Candle


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("market-data fingerprint values must be finite")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def fingerprint_candles(
    symbol: str,
    candles_by_timeframe: dict[str, list[Candle]],
) -> str:
    """Build a stable SHA-256 fingerprint for an immutable research dataset view."""
    if not symbol.strip():
        raise ValueError("symbol cannot be empty")
    payload: list[dict[str, object]] = []
    for timeframe in sorted(candles_by_timeframe):
        rows = sorted(
            (candle for candle in candles_by_timeframe[timeframe] if candle.symbol == symbol),
            key=lambda candle: candle.timestamp,
        )
        for candle in rows:
            if candle.timestamp.tzinfo is None or candle.timestamp.utcoffset() is None:
                raise ValueError("research candles must use timezone-aware timestamps")
            payload.append(
                {
                    "symbol": candle.symbol,
                    "timeframe": candle.timeframe,
                    "timestamp": candle.timestamp.astimezone(timezone.utc).isoformat(),
                    "open": _decimal_text(candle.open),
                    "high": _decimal_text(candle.high),
                    "low": _decimal_text(candle.low),
                    "close": _decimal_text(candle.close),
                    "volume": _decimal_text(candle.volume),
                }
            )
    if not payload:
        raise ValueError(f"no candles found for {symbol}")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
