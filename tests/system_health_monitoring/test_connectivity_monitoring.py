from app.system_health_monitoring.api_connectivity_monitor import APIConnectivityMonitor
from app.system_health_monitoring.exchange_connection_monitor import ExchangeConnectionMonitor
from app.system_health_monitoring.oracle_health_monitor import OracleHealthMonitor


def test_api_connectivity_monitor():
    result = APIConnectivityMonitor().check("storm_api")
    assert result.available is True


def test_exchange_connection_monitor():
    result = ExchangeConnectionMonitor().check("storm_trade")
    assert result.connected is True


def test_oracle_health_monitor():
    result = OracleHealthMonitor().check("pyth")
    assert result.healthy is True
