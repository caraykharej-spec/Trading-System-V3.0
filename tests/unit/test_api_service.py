from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.enums import SystemMode
from interfaces.api.service import TradingApiService


@dataclass(frozen=True)
class Item:
    symbol: str
    amount: Decimal


@dataclass(frozen=True)
class Performance:
    total_trades: int
    net_pnl: Decimal


def test_health_is_paper_and_serializable() -> None:
    service = TradingApiService(mode=SystemMode.PAPER)
    response = service.health()
    assert response.status_code == 200
    assert response.body == {"status": "ok", "mode": "PAPER", "version": "3.0.0-dev1"}


def test_positions_are_serialized_without_business_logic() -> None:
    service = TradingApiService(positions_provider=lambda: [Item("BTC/USD", Decimal("10.5"))])
    response = service.positions()
    assert response.status_code == 200
    assert response.body["positions"] == [{"symbol": "BTC/USD", "amount": "10.5"}]


def test_opportunity_limit_is_validated() -> None:
    service = TradingApiService(opportunities_provider=lambda: [1, 2, 3])
    assert service.opportunities(0).status_code == 400
    assert service.opportunities(101).status_code == 400
    assert service.opportunities(2).body == {"opportunities": [1, 2]}


def test_performance_requires_explicit_provider() -> None:
    response = TradingApiService().performance()
    assert response.status_code == 409
    assert response.body["error"]["code"] == "ANALYTICS_UNAVAILABLE"


def test_performance_delegates_to_read_only_provider() -> None:
    service = TradingApiService(
        analytics_provider=lambda: Performance(3, Decimal("125.50"))
    )
    response = service.performance()
    assert response.status_code == 200
    assert response.body == {
        "performance": {"total_trades": 3, "net_pnl": "125.50"}
    }


def test_cycle_requires_explicit_runner() -> None:
    service = TradingApiService()
    response = service.run_cycle()
    assert response.status_code == 409
    assert response.body["error"]["code"] == "CYCLE_UNAVAILABLE"


def test_cycle_delegates_to_application_callback() -> None:
    service = TradingApiService(cycle_runner=lambda: {"status": "COMPLETED"})
    response = service.run_cycle()
    assert response.status_code == 200
    assert response.body == {"cycle": {"status": "COMPLETED"}}
