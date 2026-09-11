from decimal import Decimal

from app.core.enums import PositionSide
from app.execution.models import OrderRequest, OrderResult, OrderStatus, OrderType
from app.live_operation.activation import LiveActivationGate, LiveActivationRequest
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
        return OrderResult(
            order_id=order.order_id,
            status=OrderStatus.ACCEPTED,
            symbol=order.symbol,
        )

    def open_positions(self) -> list[VenuePosition]:
        return []


def _order(order_id: str = "order-1") -> OrderRequest:
    return OrderRequest(
        order_id=order_id,
        symbol="BTC",
        side=PositionSide.LONG,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        requested_price=None,
        stop_loss=Decimal("90000"),
        take_profit=Decimal("110000"),
        leverage=Decimal("1"),
    )


def test_activation_is_fail_closed_without_explicit_enable():
    result = LiveActivationGate().evaluate(
        LiveActivationRequest(
            environment="production",
            go_live_approved=True,
            risk_controls_ready=True,
            health_ready=True,
            connector_ready=True,
            explicit_live_enable=False,
        )
    )
    assert result.active is False


def test_gateway_blocks_when_activation_is_not_active():
    activation = LiveActivationGate().evaluate(
        LiveActivationRequest(
            environment="production",
            go_live_approved=True,
            risk_controls_ready=True,
            health_ready=True,
            connector_ready=True,
            explicit_live_enable=False,
        )
    )
    result = LiveExecutionGateway(ReadyConnector()).submit(
        _order(), activation=activation, risk_approved=True
    )
    assert result.accepted is False
    assert result.order_result.status == OrderStatus.REJECTED


def test_gateway_accepts_once_and_blocks_duplicate_order_id():
    activation = LiveActivationGate().evaluate(
        LiveActivationRequest(
            environment="production",
            go_live_approved=True,
            risk_controls_ready=True,
            health_ready=True,
            connector_ready=True,
            explicit_live_enable=True,
        )
    )
    gateway = LiveExecutionGateway(ReadyConnector())
    first = gateway.submit(_order(), activation=activation, risk_approved=True)
    second = gateway.submit(_order(), activation=activation, risk_approved=True)
    assert first.accepted is True
    assert second.accepted is False
    assert "duplicate" in second.gateway_reason
