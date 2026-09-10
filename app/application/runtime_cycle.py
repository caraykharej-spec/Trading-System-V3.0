from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Iterable
from uuid import uuid4

from app.application.opportunity_pipeline import OpportunityPipeline
from app.core.enums import CycleStatus
from app.core.models import CycleResult, Position
from app.execution.atomic_execution import AtomicExecutionService
from app.execution.models import OrderRequest, OrderResult
from app.execution.paper_runtime import PaperSubmissionResult, PaperTradingRuntime
from app.execution.pending_order_manager import PendingOrderManager
from app.journal.service import JournalService
from app.portfolio.account import Account
from app.position.manager import (
    ExitPolicy,
    PositionManagementResult,
    manage_open_positions,
)
from app.position.settlement import PositionSettlementService
from app.recovery.reconciliation import RecoveryReconciler
from app.runtime.audit import AuditStatus, CycleAudit, CycleAuditRepository
from app.storage.account_repository import AccountRepository
from app.storage.repositories.position_repository import PositionRepository


StringIterableProvider = Callable[[], Iterable[str]] | Iterable[str]
OrderIterableProvider = Callable[[], Iterable[OrderRequest]] | Iterable[OrderRequest]
LivePriceProvider = Callable[[str], Decimal]


@dataclass
class RuntimeCycleOrchestrator:
    """Restart-safe runtime boundary for monitoring, paper orders and positions."""

    position_repository: PositionRepository
    live_price_provider: LivePriceProvider
    account: Account
    audit_repository: CycleAuditRepository
    pending_order_manager: PendingOrderManager | None = None
    exit_policy: ExitPolicy = ExitPolicy()
    recovery_reconciler: RecoveryReconciler | None = None
    recovery_order_ids_provider: StringIterableProvider | None = None
    atomic_execution_service: AtomicExecutionService | None = None
    opportunity_pipeline: OpportunityPipeline | None = None
    universe_provider: StringIterableProvider | None = None
    opportunity_top_n: int = 10
    paper_runtime: PaperTradingRuntime | None = None
    selected_orders_provider: OrderIterableProvider | None = None
    account_repository: AccountRepository | None = None
    journal_service: JournalService | None = None
    settlement_service: PositionSettlementService | None = None
    _recovery_done_for_cycle: set[str] = field(
        default_factory=set, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.opportunity_top_n < 1:
            raise ValueError("opportunity_top_n must be positive")
        if (
            self.pending_order_manager is not None
            and self.atomic_execution_service is not None
        ):
            self.pending_order_manager.fill_handler = self._persist_pending_fill

    def _persist_pending_fill(
        self, order: OrderRequest, result: OrderResult
    ) -> None:
        if self.atomic_execution_service is None:
            return
        self.atomic_execution_service.apply_fill(
            order, result, fill_id=f"fill:{result.order_id}"
        )

    @staticmethod
    def _resolve_strings(provider: StringIterableProvider) -> list[str]:
        values = provider() if callable(provider) else provider
        return list(values)

    @staticmethod
    def _resolve_orders(provider: OrderIterableProvider) -> list[OrderRequest]:
        values = provider() if callable(provider) else provider
        return list(values)

    def _run_recovery(self, cycle_id: str, notes: list[str]) -> None:
        if (
            self.recovery_reconciler is None
            or self.recovery_order_ids_provider is None
        ):
            return
        if cycle_id in self._recovery_done_for_cycle:
            return
        order_ids = self._resolve_strings(self.recovery_order_ids_provider)
        outcome = self.recovery_reconciler.reconcile(order_ids)
        notes.append(
            f"Recovery inspected={outcome.inspected_orders} "
            f"repaired_positions={outcome.repaired_positions} "
            f"issues={len(outcome.issues)}"
        )
        for issue in outcome.issues:
            notes.append(
                f"Recovery issue {issue.order_id}: "
                f"{issue.kind} - {issue.detail}"
            )
        self._recovery_done_for_cycle.add(cycle_id)

    def _run_journal_recovery(self, notes: list[str]) -> None:
        if self.journal_service is None or self.settlement_service is not None:
            return
        outcome = self.journal_service.reconcile(
            self.position_repository.list_closed()
        )
        if outcome.inspected:
            notes.append(
                f"Journal reconciliation inspected={outcome.inspected} "
                f"created={outcome.created} existing={outcome.existing}"
            )

    def _run_opportunity_pipeline(self, notes: list[str]) -> None:
        if self.opportunity_pipeline is None or self.universe_provider is None:
            return
        symbols = self._resolve_strings(self.universe_provider)
        result = self.opportunity_pipeline.evaluate(
            symbols, top_n=self.opportunity_top_n
        )
        notes.append(
            f"Opportunities evaluated={result.evaluated} "
            f"strategy_qualified={result.strategy_qualified} "
            f"context_rejected={result.context_rejected} "
            f"risk_rejected={result.risk_rejected} "
            f"portfolio_rejected={result.portfolio_rejected} "
            f"top_n={len(result.qualified)}"
        )

    def _submit_selected_orders(self, notes: list[str]) -> int:
        if self.paper_runtime is None or self.selected_orders_provider is None:
            return 0
        orders = self._resolve_orders(self.selected_orders_provider)
        submitted = 0
        for order in orders:
            result: PaperSubmissionResult = self.paper_runtime.submit(order)
            submitted += 1
            state = (
                "PENDING" if result.pending else result.result.status.value
            )
            notes.append(f"Paper order {order.order_id}: {state}")
        return submitted

    def _persist_position_management(
        self,
        *,
        positions: list[Position],
        management: PositionManagementResult,
        cycle_id: str,
        notes: list[str],
    ) -> None:
        results = management.results
        closed_ids = {result.position_id for result in results}
        positions_by_id = {
            position.position_id: position for position in positions
        }

        for position in positions:
            if position.position_id not in closed_ids:
                self.position_repository.save(position)

        if self.settlement_service is not None:
            for result in results:
                position = positions_by_id[result.position_id]
                settlement = self.settlement_service.settle(
                    position, cycle_id=cycle_id
                )
                state = "APPLIED" if settlement.applied else "EXISTING"
                notes.append(
                    f"Exit {result.position_id} reason={result.reason} "
                    f"at {result.exit_price}; P&L={result.realized_pnl}; "
                    f"settlement={state}"
                )
            return

        for result in results:
            position = positions_by_id[result.position_id]
            self.position_repository.save(position)
            self.account.apply_realized_pnl(result.realized_pnl)
            notes.append(
                f"Exit {result.position_id} reason={result.reason} "
                f"at {result.exit_price}; P&L={result.realized_pnl}"
            )
        if results and self.account_repository is not None:
            self.account_repository.save_equity(self.account.equity)
        if results and self.journal_service is not None:
            for result in results:
                position = positions_by_id[result.position_id]
                self.journal_service.record_closed_position(
                    position, cycle_id=cycle_id
                )
                notes.append(f"Journaled position {result.position_id}")

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
                    notes=existing.notes
                    + ("idempotent replay: cycle already completed",),
                )
            if existing.status is AuditStatus.STARTED:
                started_at = existing.started_at

        self.audit_repository.save(
            CycleAudit(cycle_id, AuditStatus.STARTED, started_at)
        )

        try:
            notes: list[str] = []
            self._run_recovery(cycle_id, notes)
            self._run_journal_recovery(notes)

            positions = self.position_repository.list_open()
            management = manage_open_positions(
                positions, self.live_price_provider, self.exit_policy
            )
            self._persist_position_management(
                positions=positions,
                management=management,
                cycle_id=cycle_id,
                notes=notes,
            )

            filled_orders = 0
            if self.pending_order_manager is not None:
                pending = self.pending_order_manager.check()
                filled_orders = len(pending.filled)
                for result in pending.filled:
                    notes.append(
                        f"Pending order filled: {result.order_id}"
                    )

            self._run_opportunity_pipeline(notes)
            submitted_orders = self._submit_selected_orders(notes)
            if submitted_orders:
                notes.append(f"Paper orders submitted={submitted_orders}")

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
