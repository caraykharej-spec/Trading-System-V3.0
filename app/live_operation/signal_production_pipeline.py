from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from app.application.strategy_pipeline import StrategyPipeline, StrategyPipelineResult


@dataclass(frozen=True)
class SignalProductionBatch:
    result: StrategyPipelineResult
    generated_at: datetime


class SignalProductionPipeline:
    """Production orchestration wrapper around the deterministic StrategyPipeline."""

    def __init__(self, strategy_pipeline: StrategyPipeline) -> None:
        self.strategy_pipeline = strategy_pipeline

    def generate(self, symbols: Iterable[str], top_n: int = 10) -> SignalProductionBatch:
        result = self.strategy_pipeline.evaluate(symbols, top_n=top_n)
        return SignalProductionBatch(
            result=result,
            generated_at=datetime.now(timezone.utc),
        )
