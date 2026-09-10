"""PDF renderer foundation for trading reports."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RenderedPDF:
    report_type: str
    filename: str
    created_at: datetime


class PDFRenderer:
    """Convert prepared report layouts into PDF-ready documents."""

    def render(self, report_type: str, filename: str) -> RenderedPDF:
        return RenderedPDF(
            report_type=report_type,
            filename=filename,
            created_at=datetime.utcnow(),
        )
