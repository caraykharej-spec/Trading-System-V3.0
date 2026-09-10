from decimal import Decimal

from app.analytics.dashboard_api import DashboardAPI
from app.analytics.dashboard_api_models import DashboardSnapshot


class FakeAnalytics:
    def snapshot(self):
        return DashboardSnapshot(
            total_trades=10,
            total_pnl=Decimal("50"),
            win_rate=Decimal("0.7"),
            equity=Decimal("1050"),
            drawdown=Decimal("0.1"),
        )


def test_dashboard_snapshot():
    snapshot = DashboardAPI(FakeAnalytics()).get_snapshot()

    assert snapshot.total_trades == 10
    assert snapshot.total_pnl == Decimal("50")
