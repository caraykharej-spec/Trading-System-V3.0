"""Dashboard Export API foundation.

Provides a contract layer between reporting outputs and dashboard/mobile clients.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class DashboardExportResponse:
    export_type: str
    payload: dict
    created_at: datetime


class DashboardExportAPI:
    def create_snapshot(self, payload: dict) -> DashboardExportResponse:
        return DashboardExportResponse(
            export_type="dashboard_snapshot",
            payload=payload,
            created_at=datetime.utcnow(),
        )

    def get_report_feed(self, reports: list[dict]) -> list[dict]:
        return reports
