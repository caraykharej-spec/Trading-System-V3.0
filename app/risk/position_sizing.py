from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from app.universe.contract_specs import ContractSpec


def round_quantity(quantity: Decimal, step: Decimal) -> Decimal:
    if quantity < 0 or step <= 0:
        raise ValueError("quantity and step must be non-negative/positive")
    units = (quantity / step).to_integral_value(rounding=ROUND_DOWN)
    return units * step


def calculate_position_size(*, equity: Decimal, entry: Decimal, stop_loss: Decimal, leverage: Decimal, risk_percent: Decimal, contract: ContractSpec) -> tuple[Decimal, Decimal]:
    """Return (quantity, total_amount) sized from account risk and the project's P&L model."""
    if equity <= 0 or entry <= 0 or leverage <= 0 or risk_percent <= 0:
        raise ValueError("equity, entry, leverage and risk_percent must be positive")
    distance = abs(entry - stop_loss) / entry
    if distance <= 0:
        raise ValueError("entry and stop_loss must differ")
    risk_amount = equity * risk_percent / Decimal("100")
    total_amount = risk_amount / (distance * leverage)
    quantity = round_quantity(total_amount / entry, contract.quantity_step)
    if quantity < contract.min_quantity:
        return Decimal("0"), Decimal("0")
    total_amount = quantity * entry
    return quantity, total_amount
