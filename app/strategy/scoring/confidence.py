from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ConfidenceResult:
    value: Decimal
    reasons: tuple[str, ...]


def calculate_confidence(*, data_quality: Decimal, htf_alignment: Decimal, structure_quality: Decimal, confirmation_quality: Decimal) -> ConfidenceResult:
    """Reliability of evidence; deliberately independent from opportunity score."""
    components = (data_quality, htf_alignment, structure_quality, confirmation_quality)
    if any(v < 0 or v > 100 for v in components):
        raise ValueError("confidence inputs must be between 0 and 100")
    value = (data_quality * Decimal("0.30") + htf_alignment * Decimal("0.25") + structure_quality * Decimal("0.20") + confirmation_quality * Decimal("0.25"))
    reasons = tuple(name for name, value in (("DATA", data_quality), ("HTF", htf_alignment), ("STRUCTURE", structure_quality), ("CONFIRMATION", confirmation_quality)) if value >= 90)
    return ConfidenceResult(value=min(Decimal("100"), value), reasons=reasons)
