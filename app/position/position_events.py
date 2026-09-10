from dataclasses import dataclass
from datetime import datetime


@dataclass
class PositionEvent:
    symbol: str
    event_type: str
    timestamp: datetime


class PositionEvents:
    @staticmethod
    def opened(symbol: str) -> PositionEvent:
        return PositionEvent(symbol=symbol, event_type="POSITION_OPENED", timestamp=datetime.utcnow())

    @staticmethod
    def closed(symbol: str) -> PositionEvent:
        return PositionEvent(symbol=symbol, event_type="POSITION_CLOSED", timestamp=datetime.utcnow())

    @staticmethod
    def updated(symbol: str) -> PositionEvent:
        return PositionEvent(symbol=symbol, event_type="POSITION_UPDATED", timestamp=datetime.utcnow())
