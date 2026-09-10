from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.market_data import Candle, LivePrice
from app.data.quality import detect_price_outliers, validate_candles, validate_live_price


@dataclass(frozen=True)
class ReconciliationResult:
    valid: bool
    reference: LivePrice | None = None
    spread_ratio: Decimal | None = None
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def reconcile_live_prices(
    prices: tuple[LivePrice, ...] | list[LivePrice],
    *,
    max_age_seconds: int = 120,
    max_disagreement_ratio: Decimal = Decimal("0.01"),
    now=None,
) -> ReconciliationResult:
    if not prices:
        return ReconciliationResult(False, reasons=("no provider prices",))
    if max_disagreement_ratio < 0:
        raise ValueError("max_disagreement_ratio must be non-negative")
    valid: list[LivePrice] = []
    reasons: list[str] = []
    warnings: list[str] = []
    for price in prices:
        quality = validate_live_price(price, max_age_seconds=max_age_seconds, now=now)
        if quality.valid:
            valid.append(price)
        else:
            reasons.extend(f"{price.provider}: {reason}" for reason in quality.reasons)
    if not valid:
        return ReconciliationResult(False, reasons=tuple(reasons or ("no valid provider prices",)))

    reference = sorted(valid, key=lambda p: p.provider)[0]
    deviations = [abs(p.price - reference.price) / reference.price for p in valid if reference.price > 0]
    spread = max(deviations, default=Decimal("0"))
    if spread > max_disagreement_ratio:
        reasons.append(f"provider price disagreement exceeds {max_disagreement_ratio}")
    if len(valid) == 1 and len(prices) > 1:
        warnings.append("only one provider produced a valid price")
    return ReconciliationResult(not reasons, reference, spread, tuple(reasons), tuple(warnings))


def reconcile_candles(
    series: dict[str, tuple[Candle, ...] | list[Candle]],
    *,
    expected_timeframe: str,
    max_age_seconds: int | None = None,
    now=None,
    max_close_disagreement_ratio: Decimal = Decimal("0.01"),
) -> ReconciliationResult:
    if not series:
        return ReconciliationResult(False, reasons=("no provider candle series",))
    valid: dict[str, tuple[Candle, ...]] = {}
    reasons: list[str] = []
    warnings: list[str] = []
    for provider, candles in series.items():
        quality = validate_candles(
            candles,
            expected_timeframe=expected_timeframe,
            max_age_seconds=max_age_seconds,
            now=now,
        ).merge(detect_price_outliers(candles))
        if quality.valid:
            valid[provider] = tuple(candles)
        else:
            reasons.extend(f"{provider}: {reason}" for reason in quality.reasons)
    if not valid:
        return ReconciliationResult(False, reasons=tuple(reasons or ("no valid candle series",)))

    providers = sorted(valid)
    reference_provider = providers[0]
    reference = valid[reference_provider]
    by_timestamp = {c.timestamp: c for c in reference}
    max_disagreement = Decimal("0")
    for provider in providers[1:]:
        other = {c.timestamp: c for c in valid[provider]}
        common = set(by_timestamp) & set(other)
        if not common:
            warnings.append(f"{provider}: no overlapping candle timestamps")
            continue
        for timestamp in common:
            a = by_timestamp[timestamp].close
            b = other[timestamp].close
            if a > 0:
                max_disagreement = max(max_disagreement, abs(a - b) / a)
    if max_disagreement > max_close_disagreement_ratio:
        reasons.append(f"provider candle disagreement exceeds {max_close_disagreement_ratio}")
    if len(valid) == 1 and len(series) > 1:
        warnings.append("only one provider produced a valid candle series")
    return ReconciliationResult(
        not reasons,
        None,
        max_disagreement,
        tuple(reasons),
        tuple(warnings),
    )
