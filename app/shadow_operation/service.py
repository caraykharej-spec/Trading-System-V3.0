from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Callable
from uuid import uuid4

from app.shadow_operation.repository import ShadowEvidenceRepository, StoredEvidence
from app.shadow_validation.validation import ShadowReport, ShadowValidator


Clock = Callable[[], datetime]


@dataclass
class PersistentShadowService:
    validator: ShadowValidator
    repository: ShadowEvidenceRepository
    symbols: tuple[str, ...]
    interval_seconds: int = 1800
    lease_seconds: int = 3600
    clock: Clock = lambda: datetime.now(timezone.utc)

    def __post_init__(self) -> None:
        if not 60 <= self.interval_seconds <= 86_400:
            raise ValueError("interval_seconds must be between 60 and 86400")
        if not self.interval_seconds <= self.lease_seconds <= 2 * self.interval_seconds:
            raise ValueError("lease_seconds must be between one and two intervals")

    def run_once(self) -> StoredEvidence | None:
        owner = uuid4().hex
        now = self.clock()
        if not self.repository.acquire_lease(
            owner, now, timedelta(seconds=self.lease_seconds)
        ):
            return None
        try:
            try:
                report = self.validator.run(self.symbols)
            except Exception as exc:
                report = ShadowReport(
                    status="FAIL",
                    observed_at=now.isoformat(),
                    symbols=self.symbols,
                    checks=(
                        {
                            "kind": "persistent_shadow_worker",
                            "status": "FAIL",
                            "reason": type(exc).__name__,
                        },
                    ),
                )
            return self.repository.append(report)
        finally:
            self.repository.release_lease(owner)

    def run_forever(self, stop: Event) -> None:
        while not stop.is_set():
            self.run_once()
            stop.wait(self.interval_seconds)
