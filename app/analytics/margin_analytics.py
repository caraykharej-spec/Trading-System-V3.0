"""Margin analytics foundation.

Prepared for futures exchange integrations such as Storm Trade.
"""

from dataclasses import dataclass


@dataclass
class MarginSnapshot:
    used_margin: float
    available_margin: float
    margin_ratio: float
    risk_level: str


class MarginAnalytics:
    def evaluate(self, used_margin: float, available_margin: float) -> MarginSnapshot:
        total = used_margin + available_margin
        ratio = used_margin / total if total else 0.0

        if ratio >= 0.8:
            risk = "HIGH"
        elif ratio >= 0.5:
            risk = "WARNING"
        else:
            risk = "NORMAL"

        return MarginSnapshot(
            used_margin=used_margin,
            available_margin=available_margin,
            margin_ratio=ratio,
            risk_level=risk,
        )
