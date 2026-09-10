"""Exposure analytics foundation for Phase 31.3.2.

Provides portfolio exposure calculations used by risk analytics.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class ExposureSnapshot:
    total_exposure: float
    long_exposure: float
    short_exposure: float
    concentration: Dict[str, float]


class ExposureAnalytics:
    def calculate(self, positions):
        long_exposure = 0.0
        short_exposure = 0.0
        concentration = {}

        for position in positions:
            value = abs(position.get("notional", 0.0))
            symbol = position.get("symbol", "UNKNOWN")
            side = position.get("side", "LONG")

            concentration[symbol] = concentration.get(symbol, 0.0) + value

            if side == "SHORT":
                short_exposure += value
            else:
                long_exposure += value

        return ExposureSnapshot(
            total_exposure=long_exposure + short_exposure,
            long_exposure=long_exposure,
            short_exposure=short_exposure,
            concentration=concentration,
        )
