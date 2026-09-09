from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import sqlite3

from app.core.enums import PositionSide
from app.execution.fill_repository import FillRepository
from app.execution.fills import Fill


class SQLiteFillRepository(FillRepository):
    """Append-only SQLite execution ledger with unique fill IDs."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, fill: Fill) -> None:
        existing = self.connection.execute(
            "SELECT order_id, symbol, side, quantity, price, commission, filled_at "
            "FROM fills WHERE fill_id = ?",
            (fill.fill_id,),
        ).fetchone()
        if existing is not None:
            existing_fill = self._from_row((fill.fill_id, *existing))
            if existing_fill != fill:
                raise ValueError(f"Conflicting fill: {fill.fill_id}")
            return

        if not self.connection.execute(
            "SELECT 1 FROM orders WHERE order_id = ?", (fill.order_id,)
        ).fetchone():
            raise ValueError(f"Unknown order: {fill.order_id}")

        self.connection.execute(
            """INSERT INTO fills (
                fill_id, order_id, symbol, side, quantity, price, commission, filled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fill.fill_id,
                fill.order_id,
                fill.symbol,
                fill.side.value,
                str(fill.quantity),
                str(fill.price),
                str(fill.commission),
                fill.filled_at.isoformat(),
            ),
        )
        self.connection.commit()

    def get(self, fill_id: str) -> Fill | None:
        row = self.connection.execute(
            """SELECT fill_id, order_id, symbol, side, quantity, price, commission, filled_at
               FROM fills WHERE fill_id = ?""",
            (fill_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def list_for_order(self, order_id: str) -> list[Fill]:
        rows = self.connection.execute(
            """SELECT fill_id, order_id, symbol, side, quantity, price, commission, filled_at
               FROM fills WHERE order_id = ? ORDER BY filled_at, fill_id""",
            (order_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> Fill:
        return Fill(
            fill_id=str(row[0]),
            order_id=str(row[1]),
            symbol=str(row[2]),
            side=PositionSide(str(row[3])),
            quantity=Decimal(str(row[4])),
            price=Decimal(str(row[5])),
            commission=Decimal(str(row[6])),
            filled_at=datetime.fromisoformat(str(row[7])),
        )
