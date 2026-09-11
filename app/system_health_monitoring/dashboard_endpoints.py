"""System Health Dashboard API endpoints foundation."""

from datetime import datetime


class DashboardEndpointProvider:
    @staticmethod
    def _status(component: str) -> dict[str, str]:
        return {
            "component": component,
            "status": "unknown",
            "checked_at": datetime.utcnow().isoformat(),
        }

    def runtime_status(self) -> dict[str, str]:
        return self._status("runtime")

    def data_pipeline_status(self) -> dict[str, str]:
        return self._status("data_pipeline")

    def connectivity_status(self) -> dict[str, str]:
        return self._status("connectivity")

    def exchange_status(self) -> dict[str, str]:
        return self._status("exchange")

    def oracle_status(self) -> dict[str, str]:
        return self._status("oracle")
