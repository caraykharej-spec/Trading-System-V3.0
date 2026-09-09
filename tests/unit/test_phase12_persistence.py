from datetime import datetime, timezone
from decimal import Decimal

from app.core.enums import PositionSide
from app.core.models import Position
from app.execution.models import OrderRequest, OrderResult, OrderStatus, OrderType
from app.execution.position_builder import position_from_fill
from app.storage.database import connect
from app.storage.repositories.sqlite_position_repository import SQLitePositionRepository


def test_sqlite_round_trip_preserves_take_profit(tmp_path) -> None:
    connection = connect(tmp_path / "positions.db")
    repository = SQLitePositionRepository(connection)
    position = Position(
        position_id="P-12", symbol="BTC/USDT", side=PositionSide.LONG,
        entry_price=Decimal("100"), stop_loss=Decimal("95"),
        total_amount=Decimal("100"), quantity=Decimal("2"),
        leverage=Decimal("2"), take_profit=Decimal("115"),
    )
    repository.save(position)
    loaded = repository.list_open()[0]
    assert loaded.take_profit == Decimal("115")
    assert loaded.entry_price == Decimal("100")
    connection.close()


def test_position_builder_uses_confirmed_fill_and_collateral_model() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    order = OrderRequest(
        order_id="ORD-12", symbol="BTC/USDT", side=PositionSide.LONG,
        order_type=OrderType.MARKET, quantity=Decimal("2"),
        requested_price=None, stop_loss=Decimal("90"),
        take_profit=Decimal("120"), leverage=Decimal("4"), created_at=created,
    )
    result = OrderResult(
        order_id="ORD-12", status=OrderStatus.FILLED, symbol="BTC/USDT",
        filled_price=Decimal("100"), filled_at=created,
    )
    position = position_from_fill(order, result)
    assert position.entry_price == Decimal("100")
    assert position.quantity == Decimal("2")
    assert position.total_amount == Decimal("50")
    assert position.take_profit == Decimal("120")


def test_position_builder_rejects_non_fill() -> None:
    order = OrderRequest(
        order_id="ORD-13", symbol="BTC/USDT", side=PositionSide.LONG,
        order_type=OrderType.MARKET, quantity=Decimal("1"),
        requested_price=None, stop_loss=Decimal("90"), take_profit=Decimal("110"),
    )
    result = OrderResult(
        order_id="ORD-13", status=OrderStatus.REJECTED,
        symbol="BTC/USDT", reason="rejected",
    )
    try:
        position_from_fill(order, result)
    except ValueError as exc:
        assert "non-filled" in str(exc)
    else:
        raise AssertionError("expected ValueError")
