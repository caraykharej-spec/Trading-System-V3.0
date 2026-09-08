from decimal import Decimal

from app.core.enums import PositionSide
from app.core.models import Position
from app.portfolio.account import Account


def test_equity_includes_realized_pnl() -> None:
    account = Account(starting_equity=Decimal("10000"))
    account.apply_realized_pnl(Decimal("125"))
    assert account.equity == Decimal("10125")


def test_aggregate_open_risk_uses_remaining_open_positions() -> None:
    account = Account(starting_equity=Decimal("10000"))
    positions = [
        Position(
            position_id="P1",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            total_amount=Decimal("100"),
            quantity=Decimal("1"),
            leverage=Decimal("2"),
        )
    ]
    assert account.aggregate_open_risk(positions) == Decimal("10")
