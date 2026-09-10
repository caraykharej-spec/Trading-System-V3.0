from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import sqlite3


@dataclass(frozen=True)
class AccountLedgerEntry:
    ledger_id: str
    position_id: str
    cycle_id: str | None
    realized_pnl: Decimal
    equity_before: Decimal
    equity_after: Decimal
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.ledger_id.strip() or not self.position_id.strip():
            raise ValueError("ledger_id and position_id must not be empty")
        if self.cycle_id is not None and not self.cycle_id.strip():
            raise ValueError("cycle_id must not be empty when provided")
        if self.equity_before < 0 or self.equity_after < 0:
            raise ValueError("ledger equity cannot be negative")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if self.equity_before + self.realized_pnl != self.equity_after:
            raise ValueError("ledger equity transition does not match realized P&L")


class SQLiteAccountLedgerRepository:
    """Append-only realized-P&L ledger with position-level idempotency."""

    def __init__(self, connection: sqlite3.Connection, *, auto_commit: bool = True) -> None:
        self.connection = connection
        self.auto_commit = auto_commit

    def get_for_position(self, position_id: str) -> AccountLedgerEntry | None:
        row = self.connection.execute(
            """SELECT ledger_id, position_id, cycle_id, realized_pnl, equity_before,
               equity_after, created_at FROM account_ledger WHERE position_id = ?""",
            (position_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def save(self, entry: AccountLedgerEntry) -> bool:
        existing = self.get_for_position(entry.position_id)
        if existing is not None:
            if existing == entry:
                return False
            raise ValueError(f"account ledger conflict for position {entry.position_id}")
        self.connection.execute(
            """INSERT INTO account_ledger(
                ledger_id, position_id, cycle_id, realized_pnl,
                equity_before, equity_after, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.ledger_id,
                entry.position_id,
                entry.cycle_id,
                str(entry.realized_pnl),
                str(entry.equity_before),
                str(entry.equity_after),
                entry.created_at.isoformat(),
            ),
        )
        if self.auto_commit:
            self.connection.commit()
        return True

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> AccountLedgerEntry:
        ledger_id, position_id, cycle_id, pnl, before, after, created_at = row
        return AccountLedgerEntry(
            ledger_id=str(ledger_id),
            position_id=str(position_id),
            cycle_id=str(cycle_id) if cycle_id is not None else None,
            realized_pnl=Decimal(str(pnl)),
            equity_before=Decimal(str(before)),
            equity_after=Decimal(str(after)),
            created_at=datetime.fromisoformat(str(created_at)),
        )
