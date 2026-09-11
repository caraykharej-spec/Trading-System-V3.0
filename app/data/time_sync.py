from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ClockSyncSnapshot:
    samples: int
    observed_offset_ms: float
    max_abs_offset_ms: float
    healthy: bool
    last_server_time_ms: int | None
    last_observed_at: datetime | None


class ClockSkewMonitor:
    """Track provider-vs-local timestamp skew from public market-data messages."""

    def __init__(self, *, max_allowed_skew_ms: float = 5_000.0, alpha: float = 0.2) -> None:
        if max_allowed_skew_ms <= 0:
            raise ValueError("max_allowed_skew_ms must be positive")
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0, 1]")
        self.max_allowed_skew_ms = max_allowed_skew_ms
        self.alpha = alpha
        self._samples = 0
        self._offset_ms = 0.0
        self._max_abs_offset_ms = 0.0
        self._last_server_time_ms: int | None = None
        self._last_observed_at: datetime | None = None

    def observe(
        self,
        server_time_ms: int,
        *,
        received_at: datetime | None = None,
    ) -> ClockSyncSnapshot:
        observed_at = received_at or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
        if server_time_ms <= 0:
            raise ValueError("server_time_ms must be positive")

        local_ms = observed_at.timestamp() * 1000.0
        sample_offset = float(server_time_ms) - local_ms
        if self._samples == 0:
            self._offset_ms = sample_offset
        else:
            self._offset_ms = (
                self.alpha * sample_offset + (1.0 - self.alpha) * self._offset_ms
            )
        self._samples += 1
        self._max_abs_offset_ms = max(self._max_abs_offset_ms, abs(sample_offset))
        self._last_server_time_ms = server_time_ms
        self._last_observed_at = observed_at
        return self.snapshot()

    def snapshot(self) -> ClockSyncSnapshot:
        return ClockSyncSnapshot(
            samples=self._samples,
            observed_offset_ms=self._offset_ms,
            max_abs_offset_ms=self._max_abs_offset_ms,
            healthy=self._samples > 0 and abs(self._offset_ms) <= self.max_allowed_skew_ms,
            last_server_time_ms=self._last_server_time_ms,
            last_observed_at=self._last_observed_at,
        )
