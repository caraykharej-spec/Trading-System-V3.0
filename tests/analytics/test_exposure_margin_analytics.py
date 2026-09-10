from app.analytics.exposure_analytics import ExposureAnalytics
from app.analytics.margin_analytics import MarginAnalytics


def test_exposure_calculation():
    result = ExposureAnalytics().calculate([
        {"symbol": "BTC", "side": "LONG", "notional": 1000},
        {"symbol": "ETH", "side": "SHORT", "notional": 500},
    ])

    assert result.total_exposure == 1500
    assert result.long_exposure == 1000
    assert result.short_exposure == 500


def test_margin_risk_level():
    result = MarginAnalytics().evaluate(800, 200)
    assert result.risk_level == "HIGH"
