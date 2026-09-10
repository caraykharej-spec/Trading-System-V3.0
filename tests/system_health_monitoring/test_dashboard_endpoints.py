from app.system_health_monitoring.dashboard_endpoints import DashboardEndpointProvider
from app.system_health_monitoring.health_api_response import HealthAPIResponse


def test_dashboard_endpoints():
    provider = DashboardEndpointProvider()
    response = provider.runtime_status()
    assert response["component"] == "runtime"


def test_health_api_response():
    response = HealthAPIResponse(endpoint="runtime", payload={"status": "ok"})
    assert response.is_valid()
