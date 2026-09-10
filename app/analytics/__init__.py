"""Read-only analytics derived from persisted journal facts."""

from .performance import PerformanceReport, analyze_performance
from .service import AnalyticsService

__all__ = ["AnalyticsService", "PerformanceReport", "analyze_performance"]
