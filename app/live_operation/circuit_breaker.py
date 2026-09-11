from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    state: CircuitState
    reason: str
    changed_at: datetime


class LiveTradingCircuitBreaker:
    """Emergency halt for all new production-order submission.

    CLOSED means submissions may proceed through the remaining gates. OPEN means
    all new submissions must be rejected. Reset is explicit; no automatic
    recovery is allowed at this boundary.
    """

    def __init__(self) -> None:
        self._state = CircuitState.CLOSED
        self._reason = "normal operation"
        self._changed_at = datetime.now(timezone.utc)

    @property
    def allows_submission(self) -> bool:
        return self._state == CircuitState.CLOSED

    def trip(self, reason: str) -> CircuitBreakerSnapshot:
        if not reason.strip():
            raise ValueError("circuit breaker reason is required")
        self._state = CircuitState.OPEN
        self._reason = reason.strip()
        self._changed_at = datetime.now(timezone.utc)
        return self.snapshot()

    def reset(self, reason: str) -> CircuitBreakerSnapshot:
        if not reason.strip():
            raise ValueError("reset reason is required")
        self._state = CircuitState.CLOSED
        self._reason = reason.strip()
        self._changed_at = datetime.now(timezone.utc)
        return self.snapshot()

    def snapshot(self) -> CircuitBreakerSnapshot:
        return CircuitBreakerSnapshot(
            state=self._state,
            reason=self._reason,
            changed_at=self._changed_at,
        )
