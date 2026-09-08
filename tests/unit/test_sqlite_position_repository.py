from decimal import Decimal

from app.core.enums import PositionSide
from app.core.models import Position
from app.storage.database import connect
from app.storage.repositories.sqlite_position_repository import SQLitePositionRepository


def test_position_survives_repository_reload(tmp_path) -> None:
    db = tmp_path / "trading.db"
    connection = connect(db)
    repository = SQLitePositionRepository(connection)
    position = Position(
        position_id="P-001",
        symbol="BTC/USDT",
        side=PositionSide.LONG,
        entry_price=Decimal("100"),
        stop_loss=Decimal("95"),
        total_amount=Decimal("100"),
        quantity=Decimal("1"),
        leverage=Decimal("2"),
    )
    repository.save(position)
    connection.close()

    reloaded_connection = connect(db)
    reloaded = SQLitePositionRepository(reloaded_connection).list_open()
    assert len(reloaded) == 1
    assert reloaded[0].position_id == "P-001"
    assert reloaded[0].total_amount == Decimal("100")
    assert reloaded[0].leverage == Decimal("2")
