from decimal import Decimal

from app.analytics.analytics_engine import AnalyticsEngine


def test_analytics_snapshot():
    result = AnalyticsEngine().generate_snapshot([
        {"pnl": "10"},
        {"pnl": "-5"},
    ])

    assert result.total_trades == 2
    assert result.total_pnl == Decimal("5")
    assert result.win_rate == Decimal("0.5")
