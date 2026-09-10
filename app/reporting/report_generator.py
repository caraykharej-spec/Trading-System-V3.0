"""Report Generator Core

Creates standardized trading system reports from analytics outputs.
"""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Report:
    report_type: str
    data: Dict[str, Any] = field(default_factory=dict)


class ReportGenerator:
    def generate(self, report_type: str, data: Dict[str, Any]) -> Report:
        return Report(report_type=report_type, data=data)

    def daily_trading_report(self, data: Dict[str, Any]) -> Report:
        return self.generate("daily_trading", data)

    def performance_report(self, data: Dict[str, Any]) -> Report:
        return self.generate("performance", data)

    def risk_report(self, data: Dict[str, Any]) -> Report:
        return self.generate("risk", data)

    def strategy_report(self, data: Dict[str, Any]) -> Report:
        return self.generate("strategy", data)

    def portfolio_summary(self, data: Dict[str, Any]) -> Report:
        return self.generate("portfolio_summary", data)
