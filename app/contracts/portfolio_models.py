"""Portfolio boundary contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExposureSnapshot:
    equity: float
    used_margin: float
    open_risk: float
