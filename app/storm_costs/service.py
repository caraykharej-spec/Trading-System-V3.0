from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from app.data.providers.http import ProviderError
from app.data.providers.storm import StormProvider
from app.storm_costs.models import CostValue, StormCostEstimate, StormMarketCostSnapshot, TonFeeEvidence

RATIO_SCALE = Decimal("1000000000")
NANO_TON = Decimal("1000000000")


def _mapping(record: dict[str, Any], key: str) -> dict[str, Any]:
    value = record.get(key)
    return value if isinstance(value, dict) else {}


def _scaled(value: Any, scale: Decimal, label: str) -> CostValue:
    if value in (None, ""):
        return CostValue(None, None)
    raw = str(value)
    try:
        return CostValue(Decimal(raw) / scale, raw)
    except InvalidOperation as exc:
        raise ProviderError(f"Invalid Storm {label} value: {raw}") from exc


def _integer(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        result = int(str(value))
    except ValueError as exc:
        raise ProviderError(f"Invalid Storm integer value: {value}") from exc
    return result if result > 0 else None


def parse_market_cost_snapshot(record: dict[str, Any]) -> StormMarketCostSnapshot:
    """Parse venue values without silently replacing missing costs with zero."""
    config, settings, amm = (_mapping(record, key) for key in ("config", "settings", "amm"))
    symbol = str(config.get("ticker") or config.get("name") or "").strip()
    address = str(record.get("address") or settings.get("address") or "").strip()
    if not symbol or not address:
        raise ProviderError("Storm cost record is missing symbol or market address")
    return StormMarketCostSnapshot(
        symbol=symbol,
        market_address=address,
        observed_at=StormProvider._extract_timestamp(record) or datetime.now(timezone.utc),
        protocol_fee_ratio=_scaled(settings.get("fee"), RATIO_SCALE, "ratio"),
        execution_fee_ton=_scaled(settings.get("executionFee"), NANO_TON, "TON"),
        rollover_fee_ratio=_scaled(settings.get("rolloverFee"), RATIO_SCALE, "ratio"),
        funding_period_seconds=_integer(settings.get("fundingPeriod")),
        long_funding_ratio_per_period=_scaled(amm.get("longFundingRate"), RATIO_SCALE, "ratio"),
        short_funding_ratio_per_period=_scaled(amm.get("shortFundingRate"), RATIO_SCALE, "ratio"),
        spread_ratio=_scaled(amm.get("vpiSpread"), RATIO_SCALE, "ratio"),
        max_price_impact_ratio=_scaled(settings.get("maxPriceImpact"), RATIO_SCALE, "ratio"),
        max_price_spread_ratio=_scaled(settings.get("maxPriceSpread"), RATIO_SCALE, "ratio"),
        liquidation_fee_ratio=_scaled(settings.get("liquidationFeeRatio"), RATIO_SCALE, "ratio"),
    )


class StormCostService:
    """Read-only Storm cost catalog plus deterministic cost calculations."""
    def __init__(self, provider: StormProvider | None = None) -> None:
        self.provider = provider or StormProvider()

    def snapshots(self) -> tuple[StormMarketCostSnapshot, ...]:
        return tuple(parse_market_cost_snapshot(item) for item in self.provider.list_market_records())

    def snapshot_for(self, symbol: str) -> StormMarketCostSnapshot:
        wanted = StormProvider._normalize_symbol(symbol)
        for item in self.snapshots():
            if StormProvider._normalize_symbol(item.symbol) == wanted:
                return item
        raise ProviderError(f"Storm cost snapshot not found: {symbol}")

    @staticmethod
    def protocol_fee(snapshot: StormMarketCostSnapshot, notional: Decimal) -> Decimal:
        if notional < 0:
            raise ValueError("notional cannot be negative")
        if snapshot.protocol_fee_ratio.value is None:
            raise ProviderError("Storm protocol fee is UNKNOWN")
        return notional * snapshot.protocol_fee_ratio.value

    @staticmethod
    def funding_cost(snapshot: StormMarketCostSnapshot, *, direction: str, notional: Decimal, held_seconds: int) -> Decimal:
        if notional < 0 or held_seconds < 0:
            raise ValueError("notional and held_seconds cannot be negative")
        if direction not in {"LONG", "SHORT"}:
            raise ValueError(f"Unsupported direction: {direction}")
        rate = snapshot.long_funding_ratio_per_period.value if direction == "LONG" else snapshot.short_funding_ratio_per_period.value
        if snapshot.funding_period_seconds is None or rate is None:
            raise ProviderError("Storm funding terms are UNKNOWN")
        signed_rate = rate if direction == "LONG" else -rate
        return notional * signed_rate * Decimal(held_seconds) / Decimal(snapshot.funding_period_seconds)

    @classmethod
    def estimate(cls, snapshot: StormMarketCostSnapshot, *, direction: str, notional: Decimal, held_seconds: int, ton_fee: TonFeeEvidence | None = None, apply_entry_spread: bool = True) -> StormCostEstimate:
        spread = snapshot.spread_ratio.value
        return StormCostEstimate(
            protocol_fee=cls.protocol_fee(snapshot, notional),
            funding_cost=cls.funding_cost(snapshot, direction=direction, notional=notional, held_seconds=held_seconds),
            spread_cost=notional * spread if apply_entry_spread and spread is not None else None,
            ton_network_fee=ton_fee.effective_ton if ton_fee else None,
        )

    @staticmethod
    def require_complete(snapshot: StormMarketCostSnapshot, fields: Iterable[str]) -> None:
        unknown = [name for name in fields if getattr(snapshot, name).value is None]
        if unknown:
            raise ProviderError("UNKNOWN Storm cost fields: " + ", ".join(sorted(unknown)))
