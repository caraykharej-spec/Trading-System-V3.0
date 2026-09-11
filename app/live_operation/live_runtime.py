from __future__ import annotations

from dataclasses import dataclass

from app.execution.models import OrderRequest
from app.risk.risk_pipeline import ApprovedRiskPackage
from .activation import LiveActivationGate, LiveActivationRequest, LiveActivationResult
from .exchange_connector import ExchangeProductionConnector
from .execution_gateway import LiveExecutionGateway, LiveExecutionResult
from .incident_management import IncidentManager
from .live_risk_controller import LiveRiskController, LiveRiskDecision
from .position_synchronization import LivePositionSynchronizer, PositionSyncReport
from .realtime_monitoring import LiveOperationMonitor


@dataclass(frozen=True)
class RuntimeReadiness:
    activation: LiveActivationResult
    position_sync: PositionSyncReport


class LiveTradingRuntime:
    """Composition root for Phase 35 operational controls.

    This coordinator does not bypass existing V3 strategy/risk components. It
    only coordinates production readiness, the secondary live risk gate, and
    the guarded exchange submission boundary.
    """

    def __init__(
        self,
        connector: ExchangeProductionConnector,
        position_sync: LivePositionSynchronizer,
        incidents: IncidentManager,
        monitor: LiveOperationMonitor,
        risk_controller: LiveRiskController | None = None,
    ) -> None:
        self.connector = connector
        self.position_sync = position_sync
        self.incidents = incidents
        self.monitor = monitor
        self.activation_gate = LiveActivationGate()
        self.risk_controller = risk_controller or LiveRiskController()
        self.execution_gateway = LiveExecutionGateway(connector)

    def evaluate_readiness(
        self,
        *,
        environment: str,
        go_live_approved: bool,
        risk_controls_ready: bool,
        health_ready: bool,
        explicit_live_enable: bool,
    ) -> RuntimeReadiness:
        sync_report = self.position_sync.reconcile()
        connector_status = self.connector.status()
        activation = self.activation_gate.evaluate(
            LiveActivationRequest(
                environment=environment,
                go_live_approved=go_live_approved,
                risk_controls_ready=risk_controls_ready,
                health_ready=health_ready,
                connector_ready=connector_status.ready,
                positions_synchronized=sync_report.synchronized,
                critical_incidents_clear=not self.incidents.has_critical_open_incident(),
                explicit_live_enable=explicit_live_enable,
            )
        )
        self.monitor.set_status("READY" if activation.active else "BLOCKED")
        return RuntimeReadiness(activation=activation, position_sync=sync_report)

    def submit(
        self,
        order: OrderRequest,
        risk_package: ApprovedRiskPackage,
        readiness: RuntimeReadiness,
    ) -> tuple[LiveRiskDecision, LiveExecutionResult]:
        live_risk = self.risk_controller.evaluate(risk_package)
        execution = self.execution_gateway.submit(
            order,
            activation=readiness.activation,
            risk_approved=live_risk.approved,
        )
        return live_risk, execution
