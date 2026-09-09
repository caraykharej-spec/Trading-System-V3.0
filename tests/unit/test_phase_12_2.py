from datetime import datetime, timezone
from decimal import Decimal
import sqlite3

import pytest

from app.core.enums import PositionSide
from app.execution.atomic_execution import AtomicExecutionService
from app.execution.fills import Fill
from app.execution.in_memory_fill_repository import InMemoryFillRepository
from app.execution.models import OrderRequest, OrderResult, OrderStatus, OrderType
from app.storage.database import connect
from app.storage.in_memory_account_repository import InMemoryAccountRepository
from app.storage.repositories.sqlite_account_repository import SQLiteAccountRepository
from app.storage.repositories.sqlite_fill_repository import SQLiteFillRepository
from app.storage.repositories.sqlite_order_repository import SQLiteOrderRepository
from app.storage.repositories.sqlite_position_repository import SQLitePositionRepository


def make_order(order_id: str = "o-1") -> OrderRequest:
    return OrderRequest(
        order_id=order_id,
        symbol="BTC/USD",
        side=PositionSide.LONG,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        requested_price=None,
        stop_loss=Decimal("70000"),
        take_profit=Decimal("90000"),
        leverage=Decimal("7"),
        created_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )


def make_result(order_id: str = "o-1") -> OrderResult:
    return OrderResult(
        order_id=order_id,
        status=OrderStatus.FILLED,
        symbol="BTC/USD",
        filled_price=Decimal("80000"),
        filled_at=datetime(2026, 9, 9, 12, tzinfo=timezone.utc),
    )


def test_sqlite_order_fill_and_position_persist(tmp_path):
    path = tmp_path / "state.db"
    conn = connect(path)
    orders = SQLiteOrderRepository(conn)
    fills = SQLiteFillRepository(conn)
    positions = SQLitePositionRepository(conn)

    order = make_order()
    result = make_result()
    orders.save_request(order)
    orders.save_result(result)
    service = AtomicExecutionService(conn, fills, positions)
    service.apply_fill(order, result, fill_id="f-1")
    conn.close()

    conn2 = connect(path)
    assert orders.__class__(conn2).get("o-1")[1].status is OrderStatus.FILLED
    assert len(SQLiteFillRepository(conn2).list_by_order("o-1")) == 1
    assert len(SQLitePositionRepository(conn2).list_open()) == 1


def test_atomic_service_rolls_back_position_when_writer_fails():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE fills (fill_id TEXT PRIMARY KEY, order_id TEXT, symbol TEXT, side TEXT,
            quantity TEXT, price TEXT, commission TEXT, filled_at TEXT);
        CREATE TABLE positions (position_id TEXT PRIMARY KEY, symbol TEXT, side TEXT,
            entry_price TEXT, stop_loss TEXT, total_amount TEXT, quantity TEXT, leverage TEXT,
            take_profit TEXT, status TEXT, opened_at TEXT, closed_at TEXT, exit_price TEXT,
            realized_pnl TEXT, close_reason TEXT);
    """)

    class FailingPositionWriter:
        def save(self, position):
            raise RuntimeError("position write failed")

    class FillWriter:
        def save(self, fill):
            conn.execute(
                "INSERT INTO fills VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (fill.fill_id, fill.order_id, fill.symbol, fill.side.value, str(fill.quantity),
                 str(fill.price), str(fill.commission), fill.filled_at.isoformat()),
            )

    service = AtomicExecutionService(conn, FillWriter(), FailingPositionWriter())
    with pytest.raises(RuntimeError):
        service.apply_fill(make_order(), make_result(), fill_id="f-rollback")
    assert conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 0


def test_account_equity_persists(tmp_path):
    path = tmp_path / "account.db"
    conn = connect(path)
    repo = SQLiteAccountRepository(conn)
    repo.save_equity(Decimal("9876.54"))
    conn.close()
    conn2 = connect(path)
    assert SQLiteAccountRepository(conn2).load_equity() == Decimal("9876.54")


def test_in_memory_account_rejects_negative_equity():
    with pytest.raises(ValueError):
        InMemoryAccountRepository(Decimal("-1"))
