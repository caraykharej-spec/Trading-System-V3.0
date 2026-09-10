from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from app.core.models import Position
from app.risk.risk_math import position_open_risk


@dataclass(frozen=True)
class Exposure:
    symbol: str
    notional: Decimal
    risk: Decimal


@dataclass(frozen=True)
class ExposureSnapshot:
    gross_market_exposure: Decimal
    net_market_exposure: Decimal
    collateral_committed: Decimal
    open_risk: Decimal
    pending_reserved_risk: Decimal
    futures_collateral: Decimal
    margin_utilization_percent: Decimal
    by_symbol: dict[str, Decimal]
    by_asset_class: dict[str, Decimal]
    by_quote_currency: dict[str, Decimal]


def position_risk(position: Position) -> Decimal:
    return position_open_risk(position)


def build_exposure(positions: list[Position]) -> list[Exposure]:
    return [
        Exposure(position.symbol, position.total_amount, position_risk(position))
        for position in positions
        if position.status.value == "OPEN"
    ]


def total_notional(positions: list[Position]) -> Decimal:
    """Backward-compatible collateral/notional aggregate used by existing gates."""
    return sum(
        (position.total_amount for position in positions if position.status.value == "OPEN"),
        Decimal("0"),
    )


def total_risk(positions: list[Position]) -> Decimal:
    return sum((position_risk(position) for position in positions), Decimal("0"))


def build_exposure_snapshot(
    positions: list[Position],
    *,
    equity: Decimal,
    pending_reserved_risk: Decimal = Decimal("0"),
    asset_class_by_symbol: Mapping[str, str] | None = None,
    quote_currency_by_symbol: Mapping[str, str] | None = None,
) -> ExposureSnapshot:
    if equity <= 0:
        raise ValueError("equity must be positive")
    if pending_reserved_risk < 0:
        raise ValueError("pending_reserved_risk cannot be negative")

    asset_classes = asset_class_by_symbol or {}
    quote_currencies = quote_currency_by_symbol or {}
    gross = Decimal("0")
    net = Decimal("0")
    collateral = Decimal("0")
    futures_collateral = Decimal("0")
    risk = Decimal("0")
    by_symbol: dict[str, Decimal] = {}
    by_asset_class: dict[str, Decimal] = {}
    by_quote_currency: dict[str, Decimal] = {}

    for position in positions:
        if position.status.value != "OPEN":
            continue
        market_exposure = position.total_amount * position.leverage
        signed_exposure = market_exposure if position.side.value == "LONG" else -market_exposure
        gross += market_exposure
        net += signed_exposure
        collateral += position.total_amount
        risk += position_risk(position)
        if position.leverage > 1:
            futures_collateral += position.total_amount
        by_symbol[position.symbol] = by_symbol.get(position.symbol, Decimal("0")) + signed_exposure

        asset_class = asset_classes.get(position.symbol)
        if asset_class:
            by_asset_class[asset_class] = by_asset_class.get(asset_class, Decimal("0")) + market_exposure
        quote = quote_currencies.get(position.symbol)
        if quote:
            by_quote_currency[quote] = by_quote_currency.get(quote, Decimal("0")) + signed_exposure

    margin_utilization = collateral / equity * Decimal("100")
    return ExposureSnapshot(
        gross_market_exposure=gross,
        net_market_exposure=net,
        collateral_committed=collateral,
        open_risk=risk,
        pending_reserved_risk=pending_reserved_risk,
        futures_collateral=futures_collateral,
        margin_utilization_percent=margin_utilization,
        by_symbol=by_symbol,
        by_asset_class=by_asset_class,
        by_quote_currency=by_quote_currency,
    )
