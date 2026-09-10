"""Report archive foundation for Phase 31.5."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ArchivedReport:
    report_id: str
    report_type: str
    archived_at: str


class ReportArchive:
    def archive(self, report_id: str, report_type: str) -> ArchivedReport:
        return ArchivedReport(
            report_id=report_id,
            report_type=report_type,
            archived_at=datetime.utcnow().isoformat(),
        )
