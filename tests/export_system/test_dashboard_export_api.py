from app.export_system.dashboard_export_api import DashboardExportAPI
from app.export_system.mobile_data_feed import MobileFeedProvider


def test_dashboard_snapshot_creation():
    api = DashboardExportAPI()
    result = api.create_snapshot({"risk": "normal"})
    assert result.export_type == "dashboard_snapshot"


def test_mobile_feed_generation():
    provider = MobileFeedProvider()
    result = provider.generate({"ranking": []})
    assert result.status == "ready"
