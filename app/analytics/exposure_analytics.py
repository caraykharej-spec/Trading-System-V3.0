"""Exposure analytics foundation for Phase 31.3.2.

Provides portfolio exposure calculations used by risk analytics.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass
class ExposureSnapshot:
    total_exposure: float
    long_exposure: float
    short_exposure: float
    concentration: dict[str, float]


class ExposureAnalytics:
    def calculate(self, positions: Iterable[Mapping[str, Any]]) -> ExposureSnapshot:
        long_exposure = 0.0
        short_exposure = 0.0
        concentration: dict[str, float] = {}

        for position in positions:
            value = abs(float(position.get("notional", 0.0)))
            symbol = str(position.get("symbol", "UNKNOWN"))
            side = str(position.get("side", "LONG"))

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
