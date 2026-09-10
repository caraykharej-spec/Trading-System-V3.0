from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, Sequence

from app.data.provider_router import ProviderRouter
from app.runtime.audit import AuditStatus, CycleAudit
from app.universe.contract_specs import ContractSpec
from app.universe.registry import InstrumentRegistry


class HealthState(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    NOT_READY = "NOT_READY"


@dataclass(frozen=True)
class ComponentHealth:
    name: str
    state: HealthState
    message: str
    details: dict[str, object]


@dataclass(frozen=True)
class SystemHealthReport:
    state: HealthState
    generated_at: datetime
    components: tuple[ComponentHealth, ...]

    @property
    def ready(self) -> bool:
        return self.state is not HealthState.NOT_READY


class AuditReader(Protocol):
    def latest(self) -> CycleAudit | None: ...


class PositionReader(Protocol):
    def list_open(self) -> Sequence[object]: ...


class PendingReader(Protocol):
    def list_active(self) -> Sequence[object]: ...


class SystemHealthService:
    """Passive operational diagnostics with no external network side effects."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        registry: InstrumentRegistry,
        contract_specs: dict[str, ContractSpec],
        provider_routers: tuple[ProviderRouter, ...] = (),
        audit_repository: AuditReader | None = None,
        position_repository: PositionReader | None = None,
        pending_repository: PendingReader | None = None,
    ) -> None:
        self.connection = connection
        self.registry = registry
        self.contract_specs = contract_specs
        self.provider_routers = provider_routers
        self.audit_repository = audit_repository
        self.position_repository = position_repository
        self.pending_repository = pending_repository

    def liveness(self) -> SystemHealthReport:
        component = ComponentHealth(
            "process",
            HealthState.READY,
            "application process is responsive",
            {},
        )
        return SystemHealthReport(
            HealthState.READY, datetime.now(timezone.utc), (component,)
        )

    def readiness(self) -> SystemHealthReport:
        components = (
            self._database_health(),
            self._universe_health(),
            self._provider_health(),
            self._runtime_health(),
            self._position_health(),
        )
        if any(
            component.state is HealthState.NOT_READY for component in components
        ):
            state = HealthState.NOT_READY
        elif any(
            component.state is HealthState.DEGRADED for component in components
        ):
            state = HealthState.DEGRADED
        else:
            state = HealthState.READY
        return SystemHealthReport(
            state, datetime.now(timezone.utc), components
        )

    def _database_health(self) -> ComponentHealth:
        try:
            self.connection.execute("SELECT 1").fetchone()
            account = self.connection.execute(
                "SELECT equity FROM account_state WHERE account_id = 'default'"
            ).fetchone()
            if account is None:
                return ComponentHealth(
                    "database",
                    HealthState.NOT_READY,
                    "account state is not initialized",
                    {},
                )
            return ComponentHealth(
                "database",
                HealthState.READY,
                "SQLite is queryable",
                {"equity": str(account[0])},
            )
        except sqlite3.Error as exc:
            return ComponentHealth(
                "database",
                HealthState.NOT_READY,
                "SQLite check failed",
                {"error": str(exc)},
            )

    def _universe_health(self) -> ComponentHealth:
        instruments = self.registry.all(tradable_only=True)
        missing = [
            instrument.symbol
            for instrument in instruments
            if instrument.symbol.upper() not in self.contract_specs
        ]
        if not instruments:
            return ComponentHealth(
                "universe",
                HealthState.NOT_READY,
                "tradable universe is empty",
                {},
            )
        if missing:
            return ComponentHealth(
                "universe",
                HealthState.NOT_READY,
                "contract specifications are incomplete",
                {"missing_contract_specs": missing},
            )
        return ComponentHealth(
            "universe",
            HealthState.READY,
            "tradable universe is configured",
            {"instruments": len(instruments)},
        )

    def _provider_health(self) -> ComponentHealth:
        if not self.provider_routers:
            return ComponentHealth(
                "providers",
                HealthState.DEGRADED,
                "no provider router diagnostics configured",
                {},
            )
        statuses = [
            status
            for router in self.provider_routers
            for status in router.health_snapshot()
        ]
        unique: dict[str, tuple[bool, int]] = {}
        for status in statuses:
            previous = unique.get(status.name)
            if previous is None:
                unique[status.name] = (
                    status.circuit_open,
                    status.consecutive_failures,
                )
            else:
                unique[status.name] = (
                    previous[0] and status.circuit_open,
                    max(previous[1], status.consecutive_failures),
                )
        open_names = [name for name, values in unique.items() if values[0]]
        details: dict[str, object] = {
            name: {
                "circuit_open": values[0],
                "consecutive_failures": values[1],
            }
            for name, values in sorted(unique.items())
        }
        if unique and len(open_names) == len(unique):
            return ComponentHealth(
                "providers",
                HealthState.NOT_READY,
                "all provider circuits are open",
                details,
            )
        if open_names or any(values[1] for values in unique.values()):
            return ComponentHealth(
                "providers",
                HealthState.DEGRADED,
                "one or more providers have recent failures",
                details,
            )
        return ComponentHealth(
            "providers",
            HealthState.READY,
            "provider circuits are available",
            details,
        )

    def _runtime_health(self) -> ComponentHealth:
        if self.audit_repository is None:
            return ComponentHealth(
                "runtime",
                HealthState.DEGRADED,
                "runtime audit repository is not configured",
                {},
            )
        latest = self.audit_repository.latest()
        if latest is None:
            return ComponentHealth(
                "runtime",
                HealthState.READY,
                "runtime has not executed a cycle yet",
                {"last_cycle": None},
            )
        state = (
            HealthState.DEGRADED
            if latest.status is AuditStatus.FAILED
            else HealthState.READY
        )
        return ComponentHealth(
            "runtime",
            state,
            "latest cycle failed"
            if state is HealthState.DEGRADED
            else "latest cycle completed",
            {
                "cycle_id": latest.cycle_id,
                "status": latest.status.value,
                "started_at": latest.started_at.isoformat(),
                "finished_at": (
                    latest.finished_at.isoformat()
                    if latest.finished_at
                    else None
                ),
            },
        )

    def _position_health(self) -> ComponentHealth:
        open_count = (
            len(self.position_repository.list_open())
            if self.position_repository is not None
            else 0
        )
        pending_count = (
            len(self.pending_repository.list_active())
            if self.pending_repository is not None
            else 0
        )
        return ComponentHealth(
            "portfolio_state",
            HealthState.READY,
            "runtime portfolio state is queryable",
            {"open_positions": open_count, "pending_orders": pending_count},
        )
