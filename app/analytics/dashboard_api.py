from app.analytics.dashboard_api_models import DashboardSnapshot


class DashboardAPI:
    def __init__(self, analytics_engine):
        self.analytics_engine = analytics_engine

    def get_snapshot(self) -> DashboardSnapshot:
        return self.analytics_engine.snapshot()
