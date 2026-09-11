"""Integration layer between scanner opportunities and strategy evaluation."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from app.strategy.strategy_engine import StrategySignal


@dataclass(frozen=True)
class StrategyCandidate:
    symbol: str
    opportunity_score: Decimal
    strategy_signal: StrategySignal | None


class StrategyIntegration:
    """Converts scanner outputs into strategy-ready candidates.

    The class keeps market scanning independent from strategy rules and
    provides a stable contract for ranking and risk layers.
    """

    def evaluate(
        self,
        opportunities: list[Mapping[str, object]],
    ) -> list[StrategyCandidate]:
        candidates: list[StrategyCandidate] = []

        for opportunity in opportunities:
            candidates.append(
                StrategyCandidate(
                    symbol=str(opportunity.get("symbol", "")),
                    opportunity_score=Decimal(str(opportunity.get("score", 0))),
                    strategy_signal=None,
                )
            )

        return sorted(
            candidates,
            key=lambda item: item.opportunity_score,
            reverse=True,
        )
