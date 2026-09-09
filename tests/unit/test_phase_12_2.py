from datetime import datetime, timezone
from decimal import Decimal
import sqlite3

import pytest

from app.core.enums import PositionSide
from app.execution.atomic_execution import AtomicExecutionService
from app.execution.models import OrderRequest, OrderResult, OrderStatus, OrderType
from app.storage.database import connect
from app.storage.in_memory_account_repository import InMemoryAccountRepository
from app.storage.repositories.sqlite_account_repository import SQLiteAccountRepository
from app.storage.repositories.sqlite_fill_repository import SQLiteFillRepository
from app.storage.repositories.sqlite_order_repository import SQLiteOrderRepository
from app.storage.repositories.sqlite_position_repository import SQLitePositionRepository


def make_order(order_id: str = "o-1") -> OrderRequest:
    return OrderRequest(
        order_id=order_id, symbol="BTC/USD", side=PositionSide.LONG,
        order_type=OrderType.MARKET, quantity=Decimal("0.01"), requested_price=None,
        stop_loss=Decimal("70000"), take_profit=Decimal("90000"), leverage=Decimal("7"),
        created_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )


def make_result(order_id: str = "o-1") -> OrderResult:
    return OrderResult(
        order_id=order_id, status=OrderStatus.FILLED, symbol="BTC/USD",
        filled_price=Decimal("80000"), filled_at=datetime(2026, 9, 9, 12, tzinfo=timezone.utc),
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
    service = AtomicExecutionService(conn, orders, fills, positions)
    service.apply_fill(order, result, fill_id="f-1")
    conn.close()

    conn2 = connect(path)
    persisted = SQLiteOrderRepository(conn2).get("o-1")
    assert persisted is not None and persisted[1] is not None
    assert persisted[1].status is OrderStatus.FILLED
    assert len(SQLiteFillRepository(conn2).list_for_order("o-1")) == 1
    assert len(SQLitePositionRepository(conn2).list_open()) == 1


def test_atomic_service_rolls_back_all_writes_when_position_fails(tmp_path):
    path = tmp_path / "state.db"
    conn = connect(path)
    orders = SQLiteOrderRepository(conn, auto_commit=False)
    fills = SQLiteFillRepository(conn, auto_commit=False)
    positions = SQLitePositionRepository(conn, auto_commit=False)
    order = make_order("o-rollback")
    orders.save_request(order)

    class FailingPositionWriter:
        def save(self, position):
            raise RuntimeError("position write failed")

    service = AtomicExecutionService(conn, orders, fills, FailingPositionWriter())
    with pytest.raises(RuntimeError):
        service.apply_fill(order, make_result("o-rollback"), fill_id="f-rollback")

    assert SQLiteOrderRepository(conn).get("o-rollback")[1] is None
    assert SQLiteFillRepository(conn).get("f-rollback") is None
    conn.close()


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
