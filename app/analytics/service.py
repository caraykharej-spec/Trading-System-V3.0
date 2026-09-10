from __future__ import annotations

from app.analytics.performance import PerformanceReport, analyze_performance
from app.journal.repository import JournalRepository


class AnalyticsService:
    """Read-only performance analytics over the authoritative trade journal."""

    def __init__(self, journal_repository: JournalRepository) -> None:
        self.journal_repository = journal_repository

    def performance(self, symbol: str | None = None) -> PerformanceReport:
        return analyze_performance(self.journal_repository.list_all(symbol=symbol))
