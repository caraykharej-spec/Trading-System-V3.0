"""
Phase 31.4 Report Aggregation Layer
Aggregates analytics outputs into standardized trading reports.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict


@dataclass
class AggregatedReport:
    report_type: str
    generated_at: str
    sections: Dict[str, Any] = field(default_factory=dict)


class ReportAggregator:
    def build(self, report_type: str, sections: Dict[str, Any]) -> AggregatedReport:
        return AggregatedReport(
            report_type=report_type,
            generated_at=datetime.now(timezone.utc).isoformat(),
            sections=sections,
        )

    def validate(self, report: AggregatedReport) -> bool:
        return bool(report.report_type and report.sections is not None)
