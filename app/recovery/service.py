from __future__ import annotations

from dataclasses import dataclass

from app.recovery.models import RecoveryReport, RecoveryState
from app.recovery.reconciliation import RecoveryReconciler
from app.recovery.state_machine import RecoveryStateMachine


@dataclass(frozen=True)
class RecoveryService:
    """Coordinates restart recovery without creating trading facts.

    Recovery is intentionally limited to validation and deterministic repair.
    It never creates orders, bypasses risk gates, or changes strategy output.
    """

    reconciler: RecoveryReconciler
    state_machine: RecoveryStateMachine

    def run(self, order_ids: list[str]) -> RecoveryReport:
        self.state_machine.transition(RecoveryState.LOADING_STATE)
        self.state_machine.transition(RecoveryState.VALIDATING)

        result = self.reconciler.reconcile(order_ids)

        if result.issues:
            self.state_machine.transition(RecoveryState.DEGRADED)
        else:
            self.state_machine.transition(RecoveryState.RECONCILING)
            self.state_machine.transition(RecoveryState.READY)

        return RecoveryReport(
            state=self.state_machine.state,
            inspected_orders=result.inspected_orders,
            repaired_positions=result.repaired_positions,
            warnings=tuple(
                issue.kind for issue in result.issues
            ),
        )
