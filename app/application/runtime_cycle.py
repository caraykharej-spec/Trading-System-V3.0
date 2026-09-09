from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from app.core.enums import CycleStatus
from app.core.models import CycleResult
from app.execution.atomic_execution import AtomicExecutionService
from app.execution.pending_order_manager import PendingOrderManager
from app.portfolio.account import Account
from app.position.manager import ExitPolicy, manage_open_positions
from app.recovery.reconciliation import RecoveryReconciler
from app.runtime.audit import AuditStatus, CycleAudit, CycleAuditRepository
from app.storage.repositories.position_repository import PositionRepository


@dataclass
class RuntimeCycleOrchestrator:
    """Restart-safe runtime boundary for the currently implemented stages.

    Recovery runs before position monitoring. Pending fills are persisted
    atomically before their pending-order record is removed. Re-running a
    crashed cycle therefore converges on the same durable state.
    """

    position_repository: PositionRepository
    live_price_provider: object
    account: Account
    audit_repository: CycleAuditRepository
    pending_order_manager: PendingOrderManager | None = None
    exit_policy: ExitPolicy = ExitPolicy()
    recovery_reconciler: RecoveryReconciler | None = None
    recovery_order_ids_provider: object | None = None
    atomic_execution_service: AtomicExecutionService | None = None
    _recovery_done_for_cycle: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.pending_order_manager is not None and self.atomic_execution_service is not None:
            self.pending_order_manager.fill_handler = self._persist_pending_fill

    def _persist_pending_fill(self, order: object, result: object) -> None:
        if self.atomic_execution_service is None:
            return
        self.atomic_execution_service.apply_fill(
            order, result, fill_id=f"fill:{result.order_id}"
        )

    def _run_recovery(self, cycle_id: str, notes: list[str]) -> None:
        if self.recovery_reconciler is None or self.recovery_order_ids_provider is None:
            return
        if cycle_id in self._recovery_done_for_cycle:
            return
        provider = self.recovery_order_ids_provider
        order_ids = provider() if callable(provider) else list(provider)
        outcome = self.recovery_reconciler.reconcile(list(order_ids))
        notes.append(
            f"Recovery inspected={outcome.inspected_orders} "
            f"repaired_positions={outcome.repaired_positions} "
            f"issues={len(outcome.issues)}"
        )
        for issue in outcome.issues:
            notes.append(f"Recovery issue {issue.order_id}: {issue.kind} - {issue.detail}")
        self._recovery_done_for_cycle.add(cycle_id)

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
                started_at = existing.started_at

        self.audit_repository.save(CycleAudit(cycle_id, AuditStatus.STARTED, started_at))

        try:
            notes: list[str] = []
            self._run_recovery(cycle_id, notes)

            positions = self.position_repository.list_open()
            management = manage_open_positions(
                positions, self.live_price_provider, self.exit_policy
            )

            for position in positions:
                self.position_repository.save(position)
            for result in management.results:
                self.account.apply_realized_pnl(result.realized_pnl)
                notes.append(
                    f"Exit {result.position_id} reason={result.reason} "
                    f"at {result.exit_price}; P&L={result.realized_pnl}"
                )

            filled_orders = 0
            if self.pending_order_manager is not None:
                pending = self.pending_order_manager.check()
                filled_orders = len(pending.filled)
                for result in pending.filled:
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
