"""Paper execution engine for simulated order lifecycle."""

from uuid import uuid4

from .execution_models import ExecutionRequest, ExecutionResult, ExecutionStatus


class PaperExecutionEngine:
    """Simulates execution without sending orders to an exchange."""

    def submit(self, request: ExecutionRequest) -> ExecutionResult:
        request_id = str(uuid4())

        if request.quantity <= 0:
            return ExecutionResult(
                request_id=request_id,
                status=ExecutionStatus.REJECTED,
                message="Quantity must be positive",
            )

        return ExecutionResult(
            request_id=request_id,
            status=ExecutionStatus.FILLED,
            message=f"Paper filled {request.symbol}",
        )
