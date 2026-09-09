from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app.core.enums import CycleStatus
from app.core.models import CycleResult
from app.execution.pending_order_manager import PendingOrderManager
from app.execution.position_builder import position_from_fill
from app.portfolio.account import Account
from app.position.manager import ExitPolicy, manage_open_positions
from app.runtime.audit import AuditStatus, CycleAudit, CycleAuditRepository
from app.storage.repositories.position_repository import PositionRepository


@dataclass
class RuntimeCycleOrchestrator:
    """Restart-safe runtime boundary for the currently implemented cycle stages.

    The ordering is intentional: recover persisted state, monitor exits, settle
    realized P&L, then reconcile pending limit orders. Market scanning,
    strategy, risk, portfolio and new-order execution are added by later
    runtime stages and must not bypass this boundary.
    """

    position_repository: PositionRepository
    live_price_provider: object
    account: Account
    audit_repository: CycleAuditRepository
    pending_order_manager: PendingOrderManager | None = None
    exit_policy: ExitPolicy = ExitPolicy()

    def run(self, cycle_id: str | None = None) -> CycleResult:
        cycle_id = cycle_id or str(uuid4())
        started_at = datetime.now(timezone.utc)
        existing = self.audit_repository.get(cycle_id)
        if existing is not None:
            if existing.status is AuditStatus.COMPLETED:
                return CycleResult(
                    cycle_id=existing.cycle_id,
                    status=CycleStatus.COMPLETED,
                    started_at=existing.started_at,
                    finished_at=existing.finished_at or started_at,
                    monitored_positions=existing.monitored_positions,
                    stopped_positions=existing.stopped_positions,
                    notes=existing.notes + ("idempotent replay: cycle already completed",),
                )
            if existing.status is AuditStatus.STARTED:
                # A crashed cycle can safely resume because closed positions are
                # no longer returned by list_open() and pending fills are
                # reconciled from their persisted order state.
                started_at = existing.started_at

        self.audit_repository.save(CycleAudit(cycle_id, AuditStatus.STARTED, started_at))

        try:
            positions = self.position_repository.list_open()
            management = manage_open_positions(
                positions, self.live_price_provider, self.exit_policy
            )

            for position in positions:
                self.position_repository.save(position)
            for result in management.results:
                self.account.apply_realized_pnl(result.realized_pnl)

            filled_orders = 0
            notes = [
                f"Exit {result.position_id} reason={result.reason} "
                f"at {result.exit_price}; P&L={result.realized_pnl}"
                for result in management.results
            ]

            if self.pending_order_manager is not None:
                pending = self.pending_order_manager.check()
                filled_orders = len(pending.filled)
                for result in pending.filled:
                    # The OrderRequest is not carried by OrderResult, so the
                    # current orchestrator records the fill but does not guess
                    # missing SL/TP/order metadata. A later persistent order
                    # repository will supply that authoritative request.
                    notes.append(f"Pending order filled: {result.order_id}")

            finished_at = datetime.now(timezone.utc)
            audit = CycleAudit(
                cycle_id=cycle_id,
                status=AuditStatus.COMPLETED,
                started_at=started_at,
                finished_at=finished_at,
                monitored_positions=management.monitored,
                stopped_positions=management.stop_loss_exits,
                filled_orders=filled_orders,
                notes=tuple(notes),
            )
            self.audit_repository.save(audit)

            return CycleResult(
                cycle_id=cycle_id,
                status=CycleStatus.COMPLETED,
                started_at=started_at,
                finished_at=finished_at,
                monitored_positions=management.monitored,
                stopped_positions=management.stop_loss_exits,
                notes=tuple(notes),
            )
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            self.audit_repository.save(
                CycleAudit(
                    cycle_id=cycle_id,
                    status=AuditStatus.FAILED,
                    started_at=started_at,
                    finished_at=finished_at,
                    notes=(f"{type(exc).__name__}: {exc}",),
                )
            )
            raise
