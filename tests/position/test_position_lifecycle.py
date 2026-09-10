from app.position.position import Position, PositionSide, PositionStatus
from app.position.position_manager import PositionManager


def test_position_open_and_close():
    manager = PositionManager()
    position = Position(
        symbol="BTC",
        side=PositionSide.LONG,
        quantity=1,
        entry_price=100000,
        average_price=100000,
    )

    manager.open_position(position)
    assert manager.get_position("BTC").status == PositionStatus.OPEN

    manager.close_position("BTC")
    assert manager.get_position("BTC").status == PositionStatus.CLOSED
