from decimal import Decimal

from app.core.enums import PositionSide
from app.execution.models import OrderRequest, OrderResult, OrderStatus, OrderType
from app.live_operation.activation import LiveActivationGate, LiveActivationRequest
from app.live_operation.circuit_breaker import CircuitState, LiveTradingCircuitBreaker
from app.live_operation.exchange_connector import (
    ConnectorStatus,
    ExchangeProductionConnector,
    VenuePosition,
)
from app.live_operation.execution_gateway import LiveExecutionGateway


class ReadyConnector(ExchangeProductionConnector):
    def status(self) -> ConnectorStatus:
        return ConnectorStatus("TEST", True, True, True)

    def submit_order(self, order: OrderRequest) -> OrderResult:
        return OrderResult(order.order_id, OrderStatus.ACCEPTED, order.symbol)

    def open_positions(self) -> list[VenuePosition]:
        return []


def _activation():
    return LiveActivationGate().evaluate(
        LiveActivationRequest(
            environment="production",
            go_live_approved=True,
            risk_controls_ready=True,
            health_ready=True,
            connector_ready=True,
            positions_synchronized=True,
            critical_incidents_clear=True,
            explicit_live_enable=True,
        )
    )


def _order() -> OrderRequest:
    return OrderRequest(
        order_id="halt-test-1",
        symbol="BTC",
        side=PositionSide.LONG,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        requested_price=None,
        stop_loss=Decimal("90000"),
        take_profit=Decimal("110000"),
    )


def test_circuit_breaker_blocks_gateway_submission():
    breaker = LiveTradingCircuitBreaker()
    breaker.trip("operator emergency halt")
    gateway = LiveExecutionGateway(ReadyConnector(), breaker)
    result = gateway.submit(_order(), activation=_activation(), risk_approved=True)
    assert breaker.snapshot().state == CircuitState.OPEN
    assert result.accepted is False
    assert "circuit breaker open" in result.gateway_reason


def test_circuit_breaker_requires_explicit_reset():
    breaker = LiveTradingCircuitBreaker()
    breaker.trip("exchange instability")
    breaker.reset("operator validated recovery")
    assert breaker.snapshot().state == CircuitState.CLOSED
    assert breaker.allows_submission is True
