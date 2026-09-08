from __future__ import annotations

from dataclasses import dataclass

from app.universe.instrument import Instrument


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[str, ...] = ()


def check_instrument_eligibility(instrument: Instrument) -> EligibilityResult:
    reasons: list[str] = []
    try:
        instrument.validate()
    except ValueError as exc:
        reasons.append(str(exc))
    if not instrument.tradable:
        reasons.append("instrument is not tradable")
    return EligibilityResult(not reasons, tuple(reasons))
