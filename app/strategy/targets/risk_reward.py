from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RiskReward:
    entry: Decimal
    stop_loss: Decimal
    target: Decimal
    ratio: Decimal


def calculate_risk_reward(entry: Decimal, stop_loss: Decimal, target: Decimal, direction: str) -> RiskReward:
    if direction == "LONG":
        risk = entry - stop_loss
        reward = target - entry
    elif direction == "SHORT":
        risk = stop_loss - entry
        reward = entry - target
    else:
        raise ValueError("direction must be LONG or SHORT")
    if risk <= 0 or reward <= 0:
        raise ValueError("entry, stop loss and target are directionally invalid")
    return RiskReward(entry, stop_loss, target, reward / risk)
