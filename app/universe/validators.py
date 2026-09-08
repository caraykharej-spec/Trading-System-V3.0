from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.universe.contract_specs import ContractSpec
from app.universe.instrument import Instrument


@dataclass(frozen=True)
class UniverseValidation:
    valid: bool
    reasons: tuple[str, ...] = ()


def validate_instrument_contract(instrument: Instrument, spec: ContractSpec | None) -> UniverseValidation:
    reasons: list[str] = []
    try:
        instrument.validate()
    except ValueError as exc:
        reasons.append(str(exc))
    if spec is not None:
        try:
            spec.validate()
        except ValueError as exc:
            reasons.append(str(exc))
        if spec.symbol.upper() != instrument.symbol.upper():
            reasons.append("contract spec symbol does not match instrument")
        if instrument.quantity_step is not None and instrument.quantity_step != spec.quantity_step:
            reasons.append("instrument quantity_step conflicts with contract spec")
    return UniverseValidation(not reasons, tuple(reasons))
