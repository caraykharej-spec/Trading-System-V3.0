from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock


@dataclass(frozen=True)
class AssistantModelEvent:
    provider: str
    model: str
    prompt_version: str
    outcome: str
    latency_ms: float
    evidence_count: int
    output_chars: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_type: str | None = None
    created_at: datetime = datetime.now(timezone.utc)


@dataclass(frozen=True)
class AssistantMetricsSnapshot:
    calls: int
    successes: int
    failures: int
    input_tokens: int
    output_tokens: int
    average_latency_ms: float


class AssistantTelemetry:
    """In-memory, content-free assistant telemetry.

    Prompt text, model output, evidence values, session IDs and API keys are
    deliberately excluded so observability cannot become a sensitive-data log.
    """

    def __init__(self, *, max_events: int = 500) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self._max_events = max_events
        self._events: list[AssistantModelEvent] = []
        self._lock = Lock()

    def record(self, event: AssistantModelEvent) -> None:
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]

    def events(self) -> tuple[AssistantModelEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def snapshot(self) -> AssistantMetricsSnapshot:
        events = self.events()
        successes = sum(event.outcome == "success" for event in events)
        failures = len(events) - successes
        latency = sum(event.latency_ms for event in events)
        return AssistantMetricsSnapshot(
            calls=len(events),
            successes=successes,
            failures=failures,
            input_tokens=sum(event.input_tokens or 0 for event in events),
            output_tokens=sum(event.output_tokens or 0 for event in events),
            average_latency_ms=(latency / len(events)) if events else 0.0,
        )
