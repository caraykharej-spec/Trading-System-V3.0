from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import monotonic


@dataclass
class RequestMetrics:
    """Low-cardinality, process-local HTTP RED metrics."""

    started_at: float = field(default_factory=monotonic)
    _requests: dict[tuple[str, int], int] = field(default_factory=dict, init=False)
    _duration_seconds: dict[str, float] = field(default_factory=dict, init=False)
    _in_flight: int = field(default=0, init=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def begin(self) -> float:
        with self._lock:
            self._in_flight += 1
        return monotonic()

    def finish(self, method: str, status: int, started: float) -> None:
        duration = max(0.0, monotonic() - started)
        normalized_method = method.upper() if method.upper() in {"GET", "POST"} else "OTHER"
        status_class = f"{status // 100}xx" if 100 <= status <= 599 else "other"
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            key = (normalized_method, status // 100)
            self._requests[key] = self._requests.get(key, 0) + 1
            self._duration_seconds[status_class] = (
                self._duration_seconds.get(status_class, 0.0) + duration
            )

    def render_prometheus(self) -> str:
        with self._lock:
            requests = dict(self._requests)
            durations = dict(self._duration_seconds)
            in_flight = self._in_flight
            uptime = max(0.0, monotonic() - self.started_at)
        lines = [
            "# HELP trading_api_uptime_seconds Process uptime.",
            "# TYPE trading_api_uptime_seconds gauge",
            f"trading_api_uptime_seconds {uptime:.6f}",
            "# HELP trading_api_http_requests_total HTTP requests by method and status class.",
            "# TYPE trading_api_http_requests_total counter",
        ]
        for (method, status), value in sorted(requests.items()):
            lines.append(
                'trading_api_http_requests_total{method="%s",status_class="%sxx"} %d'
                % (method, status, value)
            )
        lines.extend(
            [
                "# HELP trading_api_http_request_duration_seconds_sum Cumulative request time.",
                "# TYPE trading_api_http_request_duration_seconds_sum counter",
            ]
        )
        for status_class, duration_value in sorted(durations.items()):
            lines.append(
                'trading_api_http_request_duration_seconds_sum{status_class="%s"} %.6f'
                % (status_class, duration_value)
            )
        lines.extend(
            [
                "# HELP trading_api_http_requests_in_flight Requests currently executing.",
                "# TYPE trading_api_http_requests_in_flight gauge",
                f"trading_api_http_requests_in_flight {in_flight}",
            ]
        )
        return "\n".join(lines) + "\n"
