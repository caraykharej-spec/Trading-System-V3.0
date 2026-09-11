from decimal import Decimal

from app.core.enums import PositionSide
from app.execution.models import OrderRequest, OrderResult, OrderStatus, OrderType
from app.live_operation.exchange_connector import (
    ConnectorStatus,
    ExchangeProductionConnector,
    VenuePosition,
)
from app.live_operation.incident_management import (
    IncidentManager,
    IncidentSeverity,
    TradingIncident,
)
from app.live_operation.live_runtime import LiveTradingRuntime
from app.live_operation.position_synchronization import LivePositionSynchronizer
from app.live_operation.realtime_monitoring import LiveOperationMonitor
from app.risk.risk_pipeline import ApprovedRiskPackage


class ReadyConnector(ExchangeProductionConnector):
    def status(self) -> ConnectorStatus:
        return ConnectorStatus("TEST", True, True, True)

    def submit_order(self, order: OrderRequest) -> OrderResult:
        return OrderResult(order.order_id, OrderStatus.ACCEPTED, order.symbol)

    def open_positions(self) -> list[VenuePosition]:
        return []


def _runtime(incidents: IncidentManager | None = None) -> LiveTradingRuntime:
    connector = ReadyConnector()
    sync = LivePositionSynchronizer(connector, lambda: [])
    return LiveTradingRuntime(
        connector,
        sync,
        incidents or IncidentManager(),
        LiveOperationMonitor(),
    )


def _order() -> OrderRequest:
    return OrderRequest(
        order_id="live-1",
        symbol="BTC",
        side=PositionSide.LONG,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        requested_price=None,
        stop_loss=Decimal("90000"),
        take_profit=Decimal("110000"),
    )


def _risk() -> ApprovedRiskPackage:
    return ApprovedRiskPackage(
        symbol="BTC",
        approved=True,
        risk_score=Decimal("1"),
        position_size=Decimal("0.01"),
        state="APPROVED_FOR_EXECUTION",
    )


def test_runtime_readiness_and_guarded_submission():
    runtime = _runtime()
    readiness = runtime.evaluate_readiness(
        environment="production",
        go_live_approved=True,
        risk_controls_ready=True,
        health_ready=True,
        explicit_live_enable=True,
    )
    live_risk, execution = runtime.submit(_order(), _risk(), readiness)
    assert readiness.activation.active is True
    assert live_risk.approved is True
    assert execution.accepted is True


def test_critical_incident_blocks_activation():
    incidents = IncidentManager()
    incidents.open(
        TradingIncident(
            incident_id="critical-1",
            component="exchange",
            message="venue unavailable",
            severity=IncidentSeverity.CRITICAL,
        )
    )
    runtime = _runtime(incidents)
    readiness = runtime.evaluate_readiness(
        environment="production",
        go_live_approved=True,
        risk_controls_ready=True,
        health_ready=True,
        explicit_live_enable=True,
    )
    assert readiness.activation.active is False
    assert "critical incident" in readiness.activation.reason
