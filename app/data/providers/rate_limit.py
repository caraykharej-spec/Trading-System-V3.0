from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import monotonic, sleep


@dataclass
class PublicRateLimiter:
    requests_per_second: float
    _next_request_at: float = 0.0
    _lock: Lock = field(default_factory=Lock)

    def wait(self) -> None:
        interval = 1.0 / self.requests_per_second
        with self._lock:
            now = monotonic()
            delay = self._next_request_at - now
            if delay > 0:
                sleep(delay)
                now = monotonic()
            self._next_request_at = now + interval
