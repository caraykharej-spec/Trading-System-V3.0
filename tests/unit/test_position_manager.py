from decimal import Decimal

from app.core.enums import PositionSide, PositionStatus
from app.core.models import Position
from app.position.manager import ExitPolicy, calculate_realized_pnl, manage_open_positions


def make_position(side=PositionSide.LONG, take_profit=None):
    return Position(
        position_id="P1",
        symbol="BTC/USDT",
        side=side,
        entry_price=Decimal("100"),
        stop_loss=Decimal("95") if side is PositionSide.LONG else Decimal("105"),
        total_amount=Decimal("100"),
        quantity=Decimal("1"),
        leverage=Decimal("1"),
        take_profit=take_profit,
    )


def test_long_stop_loss_closes_and_realizes_loss():
    position = make_position()
    result = manage_open_positions([position], lambda _: Decimal("94"))
    assert result.stop_loss_exits == 1
    assert position.status is PositionStatus.STOPPED_OUT
    assert position.realized_pnl == Decimal("-6")
    assert position.close_reason == "STOP_LOSS"


def test_short_take_profit_closes_and_realizes_profit():
    position = make_position(PositionSide.SHORT, Decimal("90"))
    result = manage_open_positions([position], lambda _: Decimal("90"))
    assert result.take_profit_exits == 1
    assert position.status is PositionStatus.CLOSED
    assert position.realized_pnl == Decimal("10")
    assert position.close_reason == "TAKE_PROFIT"


def test_trailing_stop_only_moves_in_favorable_direction():
    position = make_position()
    result = manage_open_positions(
        [position],
        lambda _: Decimal("110"),
        ExitPolicy(trailing_enabled=True, trailing_distance_percent=Decimal("5")),
    )
    assert result.trailing_updates == 1
    assert position.stop_loss == Decimal("104.5")
    assert position.status is PositionStatus.OPEN


def test_pnl_applies_leverage_to_position_amount():
    position = make_position()
    position.leverage = Decimal("7")
    assert calculate_realized_pnl(position, Decimal("98")) == Decimal("-14")


def test_existing_stop_has_priority_over_take_profit():
    position = make_position(take_profit=Decimal("105"))
    result = manage_open_positions([position], lambda _: Decimal("94"))
    assert result.stop_loss_exits == 1
    assert result.take_profit_exits == 0
