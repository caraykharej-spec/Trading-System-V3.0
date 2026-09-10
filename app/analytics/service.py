from __future__ import annotations

from decimal import Decimal

from app.analytics.performance import (
    DetailedPerformanceReport,
    PerformanceReport,
    analyze_detailed_performance,
    analyze_performance,
)
from app.journal.repository import JournalRepository


class AnalyticsService:
    """Read-only performance analytics over the authoritative trade journal."""

    def __init__(self, journal_repository: JournalRepository) -> None:
        self.journal_repository = journal_repository

    def performance(self, symbol: str | None = None) -> PerformanceReport:
        return analyze_performance(self.journal_repository.list_all(symbol=symbol))

    def detailed_performance(
        self, *, starting_equity: Decimal = Decimal("10000")
    ) -> DetailedPerformanceReport:
        return analyze_detailed_performance(
            self.journal_repository.list_all(), starting_equity=starting_equity
        )
