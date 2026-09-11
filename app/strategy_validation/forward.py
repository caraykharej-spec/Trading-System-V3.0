from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class ForwardMode(str, Enum):
    PAPER = "PAPER"
    SHADOW = "SHADOW"


@dataclass(frozen=True)
class ForwardObservation:
    signal_id: str
    timestamp: datetime
    symbol: str
    direction: str
    mode: ForwardMode
    risk_approved: bool
    outcome_return_percent: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.signal_id.strip() or not self.symbol.strip():
            raise ValueError("signal_id and symbol are required")
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")


@dataclass(frozen=True)
class ForwardValidationReport:
    total_observations: int
    resolved_observations: int
    risk_approved_observations: int
    hit_rate_percent: Decimal
    mean_return_percent: Decimal
    max_consecutive_losses: int
    paper_observations: int
    shadow_observations: int


class ForwardValidationTracker:
    def __init__(self) -> None:
        self._observations: dict[str, ForwardObservation] = {}

    def record(self, observation: ForwardObservation) -> None:
        existing = self._observations.get(observation.signal_id)
        if existing is not None and existing != observation:
            raise ValueError(f"conflicting forward observation: {observation.signal_id}")
        self._observations[observation.signal_id] = observation

    def report(self) -> ForwardValidationReport:
        ordered = sorted(self._observations.values(), key=lambda item: item.timestamp)
        resolved = [
            item
            for item in ordered
            if item.risk_approved and item.outcome_return_percent is not None
        ]
        wins = sum(
            1
            for item in resolved
            if item.outcome_return_percent is not None
            and item.outcome_return_percent > 0
        )
        hit_rate = (
            Decimal(wins) / Decimal(len(resolved)) * Decimal("100")
            if resolved
            else Decimal("0")
        )
        mean_return = (
            sum(
                (
                    item.outcome_return_percent
                    for item in resolved
                    if item.outcome_return_percent is not None
                ),
                Decimal("0"),
            )
            / Decimal(len(resolved))
            if resolved
            else Decimal("0")
        )
        max_losses = 0
        current_losses = 0
        for item in resolved:
            outcome = item.outcome_return_percent
            if outcome is not None and outcome < 0:
                current_losses += 1
                max_losses = max(max_losses, current_losses)
            else:
                current_losses = 0

        return ForwardValidationReport(
            total_observations=len(ordered),
            resolved_observations=len(resolved),
            risk_approved_observations=sum(1 for item in ordered if item.risk_approved),
            hit_rate_percent=hit_rate,
            mean_return_percent=mean_return,
            max_consecutive_losses=max_losses,
            paper_observations=sum(1 for item in ordered if item.mode is ForwardMode.PAPER),
            shadow_observations=sum(1 for item in ordered if item.mode is ForwardMode.SHADOW),
        )
