"""Position lifecycle management."""

from .position import Position, PositionStatus


class PositionManager:
    def __init__(self):
        self.positions: dict[str, Position] = {}

    def open_position(self, position: Position):
        position.status = PositionStatus.OPEN
        self.positions[position.symbol] = position
        return position

    def get_position(self, symbol: str):
        return self.positions.get(symbol)

    def close_position(self, symbol: str):
        position = self.positions.get(symbol)
        if position:
            position.status = PositionStatus.CLOSED
        return position
