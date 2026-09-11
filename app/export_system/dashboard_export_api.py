"""Dashboard Export API foundation.

Provides a contract layer between reporting outputs and dashboard/mobile clients.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass
class DashboardExportResponse:
    export_type: str
    payload: dict[str, Any]
    created_at: datetime


class DashboardExportAPI:
    def create_snapshot(self, payload: Mapping[str, Any]) -> DashboardExportResponse:
        return DashboardExportResponse(
            export_type="dashboard_snapshot",
            payload=dict(payload),
            created_at=datetime.utcnow(),
        )

    def get_report_feed(self, reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return list(reports)
