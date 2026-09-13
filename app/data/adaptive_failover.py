from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock


@dataclass
class SourceHealth:
    consecutive_failures: int = 0
    cooldown_until: datetime | None = None
    last_error: str | None = None


@dataclass
class AdaptiveSourceHealth:
    """Small in-memory circuit breaker; registry order remains authoritative."""

    failure_threshold: int = 3
    cooldown_seconds: int = 300
    _states: dict[tuple[str, str], SourceHealth] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def available(self, provider: str, symbol: str) -> bool:
        with self._lock:
            state = self._states.get((provider, symbol))
            if state is None or state.cooldown_until is None:
                return True
            return datetime.now(timezone.utc) >= state.cooldown_until

    def success(self, provider: str, symbol: str) -> None:
        with self._lock:
            self._states[(provider, symbol)] = SourceHealth()

    def failure(self, provider: str, symbol: str, error: Exception) -> None:
        with self._lock:
            key = (provider, symbol)
            state = self._states.setdefault(key, SourceHealth())
            state.consecutive_failures += 1
            state.last_error = type(error).__name__
            if state.consecutive_failures >= self.failure_threshold:
                state.cooldown_until = datetime.now(timezone.utc) + timedelta(
                    seconds=self.cooldown_seconds
                )
