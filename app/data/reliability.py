from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic, sleep
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass
class ProviderHealth:
    consecutive_failures: int = 0
    opened_at: float | None = None


class CircuitOpenError(RuntimeError):
    """Raised when a provider circuit is open and requests are blocked."""


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    health: ProviderHealth = field(default_factory=ProviderHealth)

    def __post_init__(self) -> None:
        if self.failure_threshold < 1 or self.recovery_seconds < 0:
            raise ValueError("invalid circuit breaker configuration")

    @property
    def is_open(self) -> bool:
        if self.health.opened_at is None:
            return False
        if monotonic() - self.health.opened_at >= self.recovery_seconds:
            self.health.opened_at = None
            return False
        return True

    def before_call(self) -> None:
        if self.is_open:
            raise CircuitOpenError("provider circuit is open")

    def record_success(self) -> None:
        self.health = ProviderHealth()

    def record_failure(self) -> None:
        failures = self.health.consecutive_failures + 1
        opened = self.health.opened_at
        if failures >= self.failure_threshold:
            opened = monotonic()
        self.health = ProviderHealth(failures, opened)


def call_with_retry(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    backoff_seconds: float = 0.25,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
    sleeper: Callable[[float], None] = sleep,
) -> T:
    if attempts < 1 or backoff_seconds < 0:
        raise ValueError("invalid retry configuration")
    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except retry_exceptions as exc:
            last_error = exc
            if attempt + 1 < attempts:
                sleeper(backoff_seconds * (2**attempt))
    assert last_error is not None
    raise last_error
