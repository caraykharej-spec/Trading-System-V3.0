from decimal import Decimal

from app.application.runtime_cycle import RuntimeCycleOrchestrator
from app.core.enums import PositionSide, PositionStatus
from app.core.models import Position
from app.portfolio.account import Account
from app.position.manager import ExitPolicy
from app.runtime.audit import AuditStatus, InMemoryCycleAuditRepository
from app.storage.repositories.in_memory_position_repository import InMemoryPositionRepository


def make_position() -> Position:
    return Position(
        position_id="P-1",
        symbol="BTC/USDT",
        side=PositionSide.LONG,
        entry_price=Decimal("100"),
        stop_loss=Decimal("95"),
        total_amount=Decimal("100"),
        quantity=Decimal("1"),
        leverage=Decimal("1"),
        take_profit=Decimal("110"),
    )


def test_runtime_cycle_persists_completion_and_stop_out() -> None:
    positions = InMemoryPositionRepository([make_position()])
    audits = InMemoryCycleAuditRepository()
    runner = RuntimeCycleOrchestrator(
        position_repository=positions,
        live_price_provider=lambda _: Decimal("94"),
        account=Account(Decimal("1000")),
        audit_repository=audits,
    )

    result = runner.run("C-1")

    assert result.status.value == "COMPLETED"
    assert positions.list_open() == []
    assert result.stopped_positions == 1
    assert audits.get("C-1").status is AuditStatus.COMPLETED
    assert audits.get("C-1").stopped_positions == 1


def test_completed_cycle_is_idempotent() -> None:
    positions = InMemoryPositionRepository([make_position()])
    audits = InMemoryCycleAuditRepository()
    runner = RuntimeCycleOrchestrator(
        position_repository=positions,
        live_price_provider=lambda _: Decimal("94"),
        account=Account(Decimal("1000")),
        audit_repository=audits,
    )

    first = runner.run("C-2")
    equity_after_first = runner.account.equity
    second = runner.run("C-2")

    assert first.stopped_positions == 1
    assert second.stopped_positions == 1
    assert runner.account.equity == equity_after_first
    assert "idempotent replay" in second.notes[-1]


def test_failed_cycle_is_audited() -> None:
    audits = InMemoryCycleAuditRepository()
    runner = RuntimeCycleOrchestrator(
        position_repository=InMemoryPositionRepository([make_position()]),
        live_price_provider=lambda _: Decimal("0"),
        account=Account(Decimal("1000")),
        audit_repository=audits,
        exit_policy=ExitPolicy(),
    )

    try:
        runner.run("C-3")
    except ValueError:
        pass
    else:
        raise AssertionError("expected invalid live price")

    assert audits.get("C-3").status is AuditStatus.FAILED
