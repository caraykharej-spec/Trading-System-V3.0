from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.models import Position
from app.execution.models import OrderRequest, OrderResult, OrderStatus
from app.execution.position_builder import position_from_fill


class OrderStore(Protocol):
    def get(self, order_id: str) -> tuple[OrderRequest, OrderResult | None] | None: ...


class PositionStore(Protocol):
    def list_open(self) -> list[Position]: ...
    def save(self, position: Position) -> None: ...


class FillStore(Protocol):
    def list_for_order(self, order_id: str) -> list[object]: ...


@dataclass(frozen=True)
class ReconciliationIssue:
    order_id: str
    kind: str
    detail: str


@dataclass(frozen=True)
class ReconciliationResult:
    inspected_orders: int
    repaired_positions: int
    issues: tuple[ReconciliationIssue, ...]


class RecoveryReconciler:
    """Repairs deterministic execution/position gaps after restart.

    It only creates a position when the persisted order is FILLED and a fill
    exists. Existing positions are never overwritten by recovery.
    """

    def __init__(self, orders: OrderStore, fills: FillStore, positions: PositionStore) -> None:
        self.orders = orders
        self.fills = fills
        self.positions = positions

    def reconcile(self, order_ids: list[str]) -> ReconciliationResult:
        existing = {position.position_id for position in self.positions.list_open()}
        repaired = 0
        issues: list[ReconciliationIssue] = []

        for order_id in order_ids:
            record = self.orders.get(order_id)
            if record is None:
                issues.append(ReconciliationIssue(order_id, "MISSING_ORDER", "order record not found"))
                continue
            order, result = record
            fills = self.fills.list_for_order(order_id)

            if result is None:
                continue
            if result.status is not OrderStatus.FILLED:
                if fills:
                    issues.append(ReconciliationIssue(order_id, "NON_FILLED_WITH_FILL", "fill exists for a non-filled order"))
                continue
            if not fills:
                issues.append(ReconciliationIssue(order_id, "FILLED_WITHOUT_FILL", "filled order has no fill ledger record"))
                continue
            if order_id in existing:
                continue

            position = position_from_fill(order, result)
            self.positions.save(position)
            existing.add(position.position_id)
            repaired += 1

        return ReconciliationResult(len(order_ids), repaired, tuple(issues))
