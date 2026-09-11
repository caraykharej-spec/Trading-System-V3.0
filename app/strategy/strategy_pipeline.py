"""End-to-end strategy pipeline orchestration.

Connects opportunity candidates with strategy evaluation and produces
risk-review-ready signals.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.strategy.integration import StrategyCandidate
from app.strategy.strategy_engine import StrategySignal


@dataclass(frozen=True)
class StrategyPipelineResult:
    candidate: StrategyCandidate
    signal: StrategySignal | None
    status: str


class StrategyPipeline:
    """Coordinates scanner output and strategy engine contracts."""

    def process(
        self,
        candidates: list[StrategyCandidate],
        evaluator: Callable[[StrategyCandidate], StrategySignal | None],
    ) -> list[StrategyPipelineResult]:
        results: list[StrategyPipelineResult] = []

        for candidate in candidates:
            try:
                signal = evaluator(candidate)
                results.append(
                    StrategyPipelineResult(
                        candidate=candidate,
                        signal=signal,
                        status="READY_FOR_RISK_REVIEW",
                    )
                )
            except Exception as exc:
                results.append(
                    StrategyPipelineResult(
                        candidate=candidate,
                        signal=None,
                        status=f"REJECTED:{type(exc).__name__}",
                    )
                )

        return results
