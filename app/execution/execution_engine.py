from __future__ import annotations

from dataclasses import dataclass

from .models import OrderRequest, OrderResult, OrderStatus
from .paper_executor import PaperExecutor


@dataclass(frozen=True)
class ExecutionPolicy:
    paper_enabled: bool = True
    shadow_enabled: bool = True


class ExecutionEngine:
    """Execution boundary; strategy and risk decisions remain outside this layer."""

    def __init__(self, paper_executor: PaperExecutor, policy: ExecutionPolicy | None = None) -> None:
        self.paper_executor = paper_executor
        self.policy = policy or ExecutionPolicy()

    def execute(self, order: OrderRequest, mode: str = "PAPER") -> OrderResult:
        mode = mode.upper()
        if mode == "PAPER" and self.policy.paper_enabled:
            return self.paper_executor.submit(order)
        if mode == "SHADOW" and self.policy.shadow_enabled:
            return self.paper_executor.submit(order)
        return OrderResult(
            order_id=order.order_id,
            status=OrderStatus.REJECTED,
            symbol=order.symbol,
            reason=f"execution mode not enabled: {mode}",
        )
