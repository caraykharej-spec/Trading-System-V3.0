from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class LiveActivationRequest:
    environment: str
    go_live_approved: bool
    risk_controls_ready: bool
    health_ready: bool
    connector_ready: bool
    positions_synchronized: bool = True
    critical_incidents_clear: bool = True
    explicit_live_enable: bool = False


@dataclass(frozen=True)
class LiveActivationResult:
    active: bool
    reason: str
    checked_at: datetime


class LiveActivationGate:
    """Fail-closed gate for live operation activation.

    Live operation requires every prerequisite and an explicit opt-in. The gate
    does not place orders and does not handle credentials.
    """

    REQUIRED_ENVIRONMENT = "production"

    def evaluate(self, request: LiveActivationRequest) -> LiveActivationResult:
        checks = {
            "production environment required": request.environment.lower() == self.REQUIRED_ENVIRONMENT,
            "go-live approval required": request.go_live_approved,
            "risk controls not ready": request.risk_controls_ready,
            "system health not ready": request.health_ready,
            "exchange connector not ready": request.connector_ready,
            "position reconciliation not clean": request.positions_synchronized,
            "critical incident still open": request.critical_incidents_clear,
            "explicit live enable required": request.explicit_live_enable,
        }
        failed = [reason for reason, passed in checks.items() if not passed]
        if failed:
            return LiveActivationResult(
                active=False,
                reason="; ".join(failed),
                checked_at=datetime.now(timezone.utc),
            )
        return LiveActivationResult(
            active=True,
            reason="all live activation gates passed",
            checked_at=datetime.now(timezone.utc),
        )
