from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from app.core.models import Position
from app.journal.models import JournalEntry
from app.journal.repository import JournalRepository
from app.portfolio.account import Account
from app.storage.account_ledger import AccountLedgerEntry, SQLiteAccountLedgerRepository
from app.storage.account_repository import AccountRepository
from app.storage.repositories.position_repository import PositionRepository


class TransactionConnection(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True)
class SettlementResult:
    position_id: str
    realized_pnl: Decimal
    equity_before: Decimal
    equity_after: Decimal
    applied: bool


class PositionSettlementService:
    """Persist close, equity transition, ledger, and journal in one transaction.

    The append-only account ledger makes a completed settlement idempotent by
    position_id. The in-memory Account is mutated only after the database commit.
    """

    def __init__(
        self,
        *,
        connection: TransactionConnection,
        position_repository: PositionRepository,
        account_repository: AccountRepository,
        ledger_repository: SQLiteAccountLedgerRepository,
        journal_repository: JournalRepository,
        account: Account,
    ) -> None:
        self.connection = connection
        self.position_repository = position_repository
        self.account_repository = account_repository
        self.ledger_repository = ledger_repository
        self.journal_repository = journal_repository
        self.account = account

    def settle(self, position: Position, *, cycle_id: str | None = None) -> SettlementResult:
        if position.status.value == "OPEN":
            raise ValueError("cannot settle an open position")
        if position.realized_pnl is None:
            raise ValueError("closed position is missing realized_pnl")
        if position.closed_at is None:
            raise ValueError("closed position is missing closed_at")

        existing = self.ledger_repository.get_for_position(position.position_id)
        if existing is not None:
            if existing.realized_pnl != position.realized_pnl:
                raise ValueError(f"settlement conflict for position {position.position_id}")
            persisted_equity = self.account_repository.load_equity()
            if persisted_equity != existing.equity_after:
                raise ValueError(
                    f"account state conflicts with ledger for position {position.position_id}"
                )
            return SettlementResult(
                position.position_id,
                existing.realized_pnl,
                existing.equity_before,
                existing.equity_after,
                False,
            )

        equity_before = self.account_repository.load_equity()
        if self.account.equity != equity_before:
            raise ValueError("in-memory account equity is out of sync with persisted account state")
        equity_after = equity_before + position.realized_pnl
        if equity_after < 0:
            raise ValueError("settlement would make account equity negative")

        ledger = AccountLedgerEntry(
            ledger_id=f"settlement:{position.position_id}",
            position_id=position.position_id,
            cycle_id=cycle_id,
            realized_pnl=position.realized_pnl,
            equity_before=equity_before,
            equity_after=equity_after,
            created_at=datetime.now(timezone.utc),
        )
        journal = JournalEntry.from_position(position, cycle_id=cycle_id)

        try:
            self.position_repository.save(position)
            self.account_repository.save_equity(equity_after)
            self.ledger_repository.save(ledger)
            self.journal_repository.save(journal)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        self.account.apply_realized_pnl(position.realized_pnl)
        return SettlementResult(
            position.position_id,
            position.realized_pnl,
            equity_before,
            equity_after,
            True,
        )
