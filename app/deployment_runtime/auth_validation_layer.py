"""Authentication and request validation foundation for API security."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hmac import compare_digest
from math import ceil
from threading import Lock
from time import monotonic


@dataclass
class APIKey:
    key: str
    name: str
    permissions: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class ValidationResult:
    valid: bool
    reason: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AuthenticationManager:
    def __init__(self) -> None:
        self.keys: dict[str, APIKey] = {}

    def register_key(self, api_key: APIKey) -> None:
        if not api_key.key:
            raise ValueError("API key must not be empty")
        self.keys[api_key.key] = api_key

    def validate_key(self, key: str) -> bool:
        if not key:
            return False
        for stored_key, item in self.keys.items():
            if item.enabled and compare_digest(stored_key, key):
                return True
        return False


class RequestValidator:
    def validate(self, request: dict[str, object]) -> ValidationResult:
        if not request:
            return ValidationResult(False, "Empty request")
        return ValidationResult(True, "Request validated")


Clock = Callable[[], float]


class RateLimitFoundation:
    """Thread-safe fixed-window rate limiter for one API process.

    This protects a single FastAPI process. Horizontal deployments must use an
    external/shared limiter at the ingress or gateway layer.
    """

    def __init__(
        self,
        max_requests: int = 120,
        window_seconds: float = 60.0,
        *,
        clock: Clock = monotonic,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: dict[str, tuple[float, int]] = {}
        self._clock = clock
        self._lock = Lock()

    def check(self, identity: str) -> bool:
        normalized = identity or "anonymous"
        now = self._clock()
        with self._lock:
            window_start, count = self.requests.get(normalized, (now, 0))
            if now - window_start >= self.window_seconds:
                window_start, count = now, 0
            if count >= self.max_requests:
                self.requests[normalized] = (window_start, count)
                return False
            self.requests[normalized] = (window_start, count + 1)
            return True

    def retry_after(self, identity: str) -> int:
        normalized = identity or "anonymous"
        now = self._clock()
        with self._lock:
            record = self.requests.get(normalized)
            if record is None:
                return 0
            window_start, _ = record
            remaining = self.window_seconds - (now - window_start)
            return max(0, ceil(remaining))
