from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import sqlite3

from app.core.enums import PositionSide, PositionStatus
from app.core.models import Position
from app.storage.repositories.position_repository import PositionRepository


class SQLitePositionRepository(PositionRepository):
    def __init__(self, connection: sqlite3.Connection, *, auto_commit: bool = True) -> None:
        self.connection = connection
        self.auto_commit = auto_commit

    def list_open(self) -> list[Position]:
        rows = self.connection.execute(
            "SELECT position_id, symbol, side, entry_price, stop_loss, total_amount, "
            "quantity, leverage, take_profit, status, opened_at, closed_at, exit_price, "
            "realized_pnl, close_reason FROM positions WHERE status = ? ORDER BY opened_at",
            (PositionStatus.OPEN.value,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def save(self, position: Position) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO positions (
                position_id, symbol, side, entry_price, stop_loss, total_amount,
                quantity, leverage, take_profit, status, opened_at, closed_at, exit_price,
                realized_pnl, close_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                position.position_id, position.symbol, position.side.value,
                str(position.entry_price), str(position.stop_loss), str(position.total_amount),
                str(position.quantity), str(position.leverage),
                str(position.take_profit) if position.take_profit is not None else None,
                position.status.value, position.opened_at.isoformat(),
                position.closed_at.isoformat() if position.closed_at else None,
                str(position.exit_price) if position.exit_price is not None else None,
                str(position.realized_pnl) if position.realized_pnl is not None else None,
                position.close_reason,
            ),
        )
        if self.auto_commit:
            self.connection.commit()

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> Position:
        (
            position_id, symbol, side, entry_price, stop_loss, total_amount,
            quantity, leverage, take_profit, status, opened_at, closed_at, exit_price,
            realized_pnl, close_reason,
        ) = row
        return Position(
            position_id=str(position_id), symbol=str(symbol), side=PositionSide(str(side)),
            entry_price=Decimal(str(entry_price)), stop_loss=Decimal(str(stop_loss)),
            total_amount=Decimal(str(total_amount)), quantity=Decimal(str(quantity)),
            leverage=Decimal(str(leverage)),
            take_profit=Decimal(str(take_profit)) if take_profit is not None else None,
            status=PositionStatus(str(status)), opened_at=datetime.fromisoformat(str(opened_at)),
            closed_at=datetime.fromisoformat(str(closed_at)) if closed_at else None,
            exit_price=Decimal(str(exit_price)) if exit_price is not None else None,
            realized_pnl=Decimal(str(realized_pnl)) if realized_pnl is not None else None,
            close_reason=str(close_reason) if close_reason else None,
        )
