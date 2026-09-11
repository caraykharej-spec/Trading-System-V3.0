"""Phase 35 live trading operation framework.

The package is fail-closed by design: live execution is never enabled merely by
constructing these components. Activation requires explicit readiness evidence
and an execution connector that reports itself ready.
"""

from .activation import LiveActivationGate, LiveActivationRequest, LiveActivationResult
from .execution_gateway import LiveExecutionGateway, LiveExecutionResult

__all__ = [
    "LiveActivationGate",
    "LiveActivationRequest",
    "LiveActivationResult",
    "LiveExecutionGateway",
    "LiveExecutionResult",
]
