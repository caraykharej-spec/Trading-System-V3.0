from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class StrategyRules:
    min_rr: Decimal = Decimal("2.5")
    min_score: Decimal = Decimal("90")
    min_confidence: Decimal = Decimal("90")


DEFAULT_RULES = StrategyRules()
