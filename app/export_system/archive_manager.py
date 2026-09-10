"""Report archive integration foundation."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ArchivedExport:
    export_id: str
    export_type: str
    archived_at: datetime


class ArchiveManager:
    def archive(self, export_id: str, export_type: str) -> ArchivedExport:
        return ArchivedExport(
            export_id=export_id,
            export_type=export_type,
            archived_at=datetime.utcnow(),
        )
