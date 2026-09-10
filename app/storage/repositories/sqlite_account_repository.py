from __future__ import annotations

import sqlite3
from decimal import Decimal

from app.storage.account_repository import AccountRepository


class SQLiteAccountRepository(AccountRepository):
    """SQLite-backed single-account equity state."""

    def __init__(self, connection: sqlite3.Connection, *, auto_commit: bool = True) -> None:
        self.connection = connection
        self.auto_commit = auto_commit

    def load_equity(self) -> Decimal:
        row = self.connection.execute(
            "SELECT equity FROM account_state WHERE account_id = ?", ("default",)
        ).fetchone()
        if row is None:
            raise ValueError("account state is not initialized")
        return Decimal(str(row[0]))

    def save_equity(self, equity: Decimal) -> None:
        if equity < 0:
            raise ValueError("equity cannot be negative")
        self.connection.execute(
            """INSERT INTO account_state(account_id, equity)
               VALUES (?, ?)
               ON CONFLICT(account_id) DO UPDATE SET equity = excluded.equity""",
            ("default", str(equity)),
        )
        if self.auto_commit:
            self.connection.commit()
