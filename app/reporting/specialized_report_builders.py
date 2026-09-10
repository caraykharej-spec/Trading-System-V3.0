"""Specialized report builders for Phase 31.4.

Provides builders for daily trading, performance, risk,
strategy and portfolio summary reports.
"""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class SpecializedReport:
    report_type: str
    sections: Dict[str, Any] = field(default_factory=dict)


class DailyTradingReportBuilder:
    def build(self, data: Dict[str, Any]) -> SpecializedReport:
        return SpecializedReport("daily_trading", {"trading": data})


class PerformanceReportBuilder:
    def build(self, data: Dict[str, Any]) -> SpecializedReport:
        return SpecializedReport("performance", {"performance": data})


class RiskReportBuilder:
    def build(self, data: Dict[str, Any]) -> SpecializedReport:
        return SpecializedReport("risk", {"risk": data})


class StrategyReportBuilder:
    def build(self, data: Dict[str, Any]) -> SpecializedReport:
        return SpecializedReport("strategy", {"strategy": data})


class PortfolioSummaryGenerator:
    def build(self, data: Dict[str, Any]) -> SpecializedReport:
        return SpecializedReport("portfolio_summary", {"portfolio": data})


class ReportValidator:
    def validate(self, report: SpecializedReport) -> bool:
        return bool(report.report_type and isinstance(report.sections, dict))
