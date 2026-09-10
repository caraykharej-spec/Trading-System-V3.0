from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import sqlite3

from app.core.enums import PositionSide
from app.journal.models import JournalEntry
from app.journal.repository import JournalRepository


_COLUMNS = (
    "position_id, cycle_id, symbol, side, entry_price, exit_price, stop_loss, take_profit, "
    "total_amount, quantity, leverage, realized_pnl, opened_at, closed_at, close_reason, "
    "decision_snapshot"
)


class SQLiteJournalRepository(JournalRepository):
    def __init__(self, connection: sqlite3.Connection, *, auto_commit: bool = True) -> None:
        self.connection = connection
        self.auto_commit = auto_commit

    def save(self, entry: JournalEntry) -> bool:
        existing = self.get(entry.position_id)
        if existing is not None:
            if existing == entry:
                return False
            raise ValueError(f"journal conflict for position {entry.position_id}")
        self.connection.execute(
            """INSERT INTO trade_journal (
                position_id, cycle_id, symbol, side, entry_price, exit_price, stop_loss,
                take_profit, total_amount, quantity, leverage, realized_pnl, opened_at,
                closed_at, close_reason, decision_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.position_id,
                entry.cycle_id,
                entry.symbol,
                entry.side.value,
                str(entry.entry_price),
                str(entry.exit_price),
                str(entry.stop_loss),
                str(entry.take_profit) if entry.take_profit is not None else None,
                str(entry.total_amount),
                str(entry.quantity),
                str(entry.leverage),
                str(entry.realized_pnl),
                entry.opened_at.isoformat(),
                entry.closed_at.isoformat(),
                entry.close_reason,
                entry.decision_snapshot,
            ),
        )
        if self.auto_commit:
            self.connection.commit()
        return True

    def get(self, position_id: str) -> JournalEntry | None:
        row = self.connection.execute(
            f"SELECT {_COLUMNS} FROM trade_journal WHERE position_id = ?",
            (position_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_all(self, symbol: str | None = None) -> list[JournalEntry]:
        if symbol is None:
            rows = self.connection.execute(
                f"SELECT {_COLUMNS} FROM trade_journal ORDER BY closed_at, position_id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                f"SELECT {_COLUMNS} FROM trade_journal WHERE symbol = ? "
                "ORDER BY closed_at, position_id",
                (symbol,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> JournalEntry:
        (
            position_id,
            cycle_id,
            symbol,
            side,
            entry_price,
            exit_price,
            stop_loss,
            take_profit,
            total_amount,
            quantity,
            leverage,
            realized_pnl,
            opened_at,
            closed_at,
            close_reason,
            decision_snapshot,
        ) = row
        return JournalEntry(
            position_id=str(position_id),
            cycle_id=str(cycle_id) if cycle_id is not None else None,
            symbol=str(symbol),
            side=PositionSide(str(side)),
            entry_price=Decimal(str(entry_price)),
            exit_price=Decimal(str(exit_price)),
            stop_loss=Decimal(str(stop_loss)),
            take_profit=Decimal(str(take_profit)) if take_profit is not None else None,
            total_amount=Decimal(str(total_amount)),
            quantity=Decimal(str(quantity)),
            leverage=Decimal(str(leverage)),
            realized_pnl=Decimal(str(realized_pnl)),
            opened_at=datetime.fromisoformat(str(opened_at)),
            closed_at=datetime.fromisoformat(str(closed_at)),
            close_reason=str(close_reason),
            decision_snapshot=(str(decision_snapshot) if decision_snapshot is not None else None),
        )
