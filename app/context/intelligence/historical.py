from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Mapping, Sequence

from app.context.models import NewsImpact
from app.data.market_data import Candle

from .models import EventIntelligence, IntelligenceCategory, NewsIntelligence


@dataclass(frozen=True)
class HistoricalImpactObservation:
    canonical_key: str
    symbol: str
    category: IntelligenceCategory
    impact: NewsImpact
    forward_return_percent: Decimal
    directionally_correct: bool


@dataclass(frozen=True)
class HistoricalImpactReport:
    observations: tuple[HistoricalImpactObservation, ...]

    @property
    def observation_count(self) -> int:
        return len(self.observations)

    @property
    def directional_hit_rate_percent(self) -> Decimal:
        if not self.observations:
            return Decimal("0")
        hits = sum(1 for item in self.observations if item.directionally_correct)
        return Decimal(hits) / Decimal(len(self.observations)) * Decimal("100")

    @property
    def mean_absolute_return_percent(self) -> Decimal:
        if not self.observations:
            return Decimal("0")
        total = sum((abs(item.forward_return_percent) for item in self.observations), Decimal("0"))
        return total / Decimal(len(self.observations))


@dataclass(frozen=True)
class HistoricalEventImpactObservation:
    event_id: str
    symbol: str
    category: IntelligenceCategory
    forward_return_percent: Decimal


@dataclass(frozen=True)
class HistoricalEventImpactReport:
    observations: tuple[HistoricalEventImpactObservation, ...]

    @property
    def observation_count(self) -> int:
        return len(self.observations)

    @property
    def mean_absolute_return_percent(self) -> Decimal:
        if not self.observations:
            return Decimal("0")
        total = sum((abs(item.forward_return_percent) for item in self.observations), Decimal("0"))
        return total / Decimal(len(self.observations))


def _forward_return(
    candles: Sequence[Candle],
    start: datetime,
    horizon: timedelta,
) -> Decimal | None:
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    anchor = next((candle for candle in ordered if candle.timestamp >= start), None)
    future = next((candle for candle in ordered if candle.timestamp >= start + horizon), None)
    if anchor is None or future is None or anchor.close <= 0:
        return None
    return (future.close - anchor.close) / anchor.close * Decimal("100")


class HistoricalImpactEvaluator:
    def evaluate(
        self,
        intelligence: Sequence[NewsIntelligence],
        candles_by_symbol: Mapping[str, Sequence[Candle]],
        *,
        horizon: timedelta = timedelta(hours=1),
    ) -> HistoricalImpactReport:
        if horizon.total_seconds() <= 0:
            raise ValueError("horizon must be positive")
        observations: list[HistoricalImpactObservation] = []
        for item in intelligence:
            if item.impact not in {NewsImpact.SUPPORTIVE, NewsImpact.ADVERSE}:
                continue
            for symbol in item.symbols:
                change = _forward_return(candles_by_symbol.get(symbol, ()), item.published_at, horizon)
                if change is None:
                    continue
                correct = change > 0 if item.impact is NewsImpact.SUPPORTIVE else change < 0
                observations.append(
                    HistoricalImpactObservation(
                        canonical_key=item.canonical_key,
                        symbol=symbol,
                        category=item.category,
                        impact=item.impact,
                        forward_return_percent=change,
                        directionally_correct=correct,
                    )
                )
        return HistoricalImpactReport(tuple(observations))

    def evaluate_events(
        self,
        events: Sequence[EventIntelligence],
        candles_by_symbol: Mapping[str, Sequence[Candle]],
        *,
        horizon: timedelta = timedelta(hours=1),
    ) -> HistoricalEventImpactReport:
        if horizon.total_seconds() <= 0:
            raise ValueError("horizon must be positive")
        observations: list[HistoricalEventImpactObservation] = []
        for item in events:
            for symbol in item.event.symbols:
                change = _forward_return(
                    candles_by_symbol.get(symbol, ()),
                    item.event.event_time,
                    horizon,
                )
                if change is None:
                    continue
                observations.append(
                    HistoricalEventImpactObservation(
                        event_id=item.event.event_id,
                        symbol=symbol,
                        category=item.category,
                        forward_return_percent=change,
                    )
                )
        return HistoricalEventImpactReport(tuple(observations))
