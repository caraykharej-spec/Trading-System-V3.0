from decimal import Decimal

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
from app.live_operation.live_risk_controller import LiveRiskController, LiveRiskLimits
from app.live_operation.operations_dashboard import TradingOperationsDashboard
from app.live_operation.position_synchronization import (
    LivePositionSynchronizer,
    LocalPositionSnapshot,
)
from app.live_operation.realtime_monitoring import LiveOperationMonitor
from app.risk.risk_pipeline import ApprovedRiskPackage


class PositionConnector(ExchangeProductionConnector):
    def status(self) -> ConnectorStatus:
        return ConnectorStatus("TEST", True, True, True)

    def submit_order(self, order):  # pragma: no cover - not used here
        raise NotImplementedError

    def open_positions(self) -> list[VenuePosition]:
        return [VenuePosition("BTC", Decimal("1"), Decimal("100"), "LONG")]


def test_live_risk_controller_accepts_core_approved_package():
    controller = LiveRiskController(
        LiveRiskLimits(max_risk_score=Decimal("10"), max_position_size=Decimal("2"))
    )
    decision = controller.evaluate(
        ApprovedRiskPackage(
            symbol="BTC",
            approved=True,
            risk_score=Decimal("5"),
            position_size=Decimal("1"),
            state="APPROVED_FOR_EXECUTION",
        )
    )
    assert decision.approved is True


def test_position_sync_reports_mismatch_without_mutating():
    synchronizer = LivePositionSynchronizer(
        PositionConnector(),
        lambda: [LocalPositionSnapshot("BTC", Decimal("2"), Decimal("100"), "LONG")],
    )
    report = synchronizer.reconcile()
    assert report.synchronized is False
    assert report.mismatches[0].field == "quantity"


def test_dashboard_surfaces_critical_incident():
    monitor = LiveOperationMonitor()
    monitor.set_status("RUNNING")
    monitor.record("cycle_latency", 12.5, "ms")
    incidents = IncidentManager()
    incidents.open(
        TradingIncident(
            incident_id="inc-1",
            component="exchange",
            message="connection lost",
            severity=IncidentSeverity.CRITICAL,
        )
    )
    snapshot = TradingOperationsDashboard(monitor, incidents).snapshot()
    assert snapshot.live_status == "RUNNING"
    assert snapshot.metric_count == 1
    assert snapshot.critical_incident_open is True
